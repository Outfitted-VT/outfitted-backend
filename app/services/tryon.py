"""Virtual try-on: put a whole outfit, or separate pieces, onto a photo of yourself."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.images import InvalidImageError, to_jpeg
from app.models.fit import Fit
from app.models.image import Image
from app.models.tryon import TryOn, TryOnPiece
from app.models.user import User
from app.repositories import fit as fit_repository
from app.repositories import image as image_repository
from app.repositories import tryon as tryon_repository
from app.schemas.tryon import TryOnCreate
from app.services.image import ImageNotFoundError, get_owned_images, upload_image
from app.storage import Storage
from app.tryon import Garment, TryOnBlockedError, TryOnGenerator, TryOnUnsupportedError


class DailyLimitReachedError(Exception):
    pass


class FitTryOnNotAllowedError(Exception):
    """The fit's author turned off try-ons for it, or the viewer can't see it."""


def _shared_clothing_ids(db: Session, user: User, fit_id: uuid.UUID) -> set[uuid.UUID]:
    """Images of someone else's fit the user may try on: its photos and the clothing photos of
    the try-on it came from (never that try-on's person photo)."""
    fit: Fit | None = fit_repository.get(db, fit_id)
    if fit is None or not fit.author.is_active:
        raise FitTryOnNotAllowedError
    if fit.user_id != user.id and (fit.privacy_tier == "vault" or not fit.allow_friend_try_on):
        raise FitTryOnNotAllowedError
    ids = {image.id for image in fit.images}
    if fit.tryon is not None:
        if fit.tryon.outfit_image_id:
            ids.add(fit.tryon.outfit_image_id)
        ids.update(piece.image_id for piece in fit.tryon.pieces if piece.image_id)
    return ids


def _clothing_images(
    db: Session, user: User, image_ids: list[uuid.UUID], shared: set[uuid.UUID]
) -> list[Image]:
    """Load the clothing photos in order: each must be the user's own or in `shared`."""
    images = {image.id: image for image in image_repository.get_many(db, image_ids)}
    for image_id in image_ids:
        image = images.get(image_id)
        if image is None or (image.owner_id != user.id and image_id not in shared):
            raise ImageNotFoundError
    return [images[i] for i in image_ids]


def create_tryon(
    db: Session,
    storage: Storage,
    generator: TryOnGenerator,
    user: User,
    data: TryOnCreate,
) -> TryOn:
    """Generate the try-on and store the result as a new image the user owns.

    The person photo must be the user's. Clothing photos must be too, unless `fit_id` names a
    fit they may try on ("Try this look"): then that fit's photos and its try-on's clothing
    photos are allowed as well.

    Raises ImageNotFoundError if an image can't be used, FitTryOnNotAllowedError,
    TryOnUnsupportedError if the model can't take this many photos, DailyLimitReachedError,
    and TryOnError from the generator.
    """
    pieces = data.pieces or []
    clothing_ids = [data.outfit_image_id] if data.outfit_image_id else [p.image_id for p in pieces]
    [person] = get_owned_images(db, user, [data.person_image_id])
    shared = _shared_clothing_ids(db, user, data.fit_id) if data.fit_id else set()
    clothing = _clothing_images(db, user, clothing_ids, shared)

    if len(clothing) > generator.max_garments:
        raise TryOnUnsupportedError(
            "Try-on can only use one photo right now. Choose 'Entire fit' instead."
        )

    since = datetime.now(UTC) - timedelta(days=1)
    if tryon_repository.count_since(db, user.id, since) >= settings.TRYON_DAILY_LIMIT:
        raise DailyLimitReachedError

    # A whole-outfit photo has no slot; each piece has one.
    slots = [piece.slot.value for piece in pieces] if pieces else [None]
    garments = [
        Garment(jpeg=to_jpeg(storage.read(image.storage_key)), slot=slot)
        for image, slot in zip(clothing, slots, strict=True)
    ]
    result = generator.generate(to_jpeg(storage.read(person.storage_key)), garments)
    try:
        # Re-encoded like any upload: WebP, at most 2048px, metadata stripped.
        result_image = upload_image(db, storage, user, result, generated=True)
    except InvalidImageError:
        raise TryOnBlockedError("We couldn't create a try-on from these photos") from None

    if pieces:
        outfit_image_id = None
        tryon_pieces = [
            TryOnPiece(position=position, slot=piece.slot.value, image_id=image.id)
            for position, (piece, image) in enumerate(zip(pieces, clothing, strict=True))
        ]
    else:
        outfit_image_id, tryon_pieces = clothing[0].id, []

    tryon = TryOn(
        user_id=user.id,
        person_image_id=person.id,
        outfit_image_id=outfit_image_id,
        result_image_id=result_image.id,
        model=settings.TRYON_MODEL,
        pieces=tryon_pieces,
    )
    tryon_repository.add(db, tryon)
    db.commit()
    return tryon
