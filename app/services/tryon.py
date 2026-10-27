"""Virtual try-on: put a whole outfit, or separate pieces, onto a photo of yourself."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.images import InvalidImageError, to_jpeg
from app.models.tryon import TryOn, TryOnPiece
from app.models.user import User
from app.repositories import tryon as tryon_repository
from app.schemas.tryon import TryOnCreate
from app.services.image import get_owned_images, upload_image
from app.storage import Storage
from app.tryon import Garment, TryOnBlockedError, TryOnGenerator, TryOnUnsupportedError


class DailyLimitReachedError(Exception):
    pass


def create_tryon(
    db: Session,
    storage: Storage,
    generator: TryOnGenerator,
    user: User,
    data: TryOnCreate,
) -> TryOn:
    """Generate the try-on and store the result as a new image the user owns.

    Raises ImageNotFoundError if any image isn't the user's, TryOnUnsupportedError if the
    model can't take this many photos, DailyLimitReachedError, and TryOnError from the
    generator.
    """
    pieces = data.pieces or []
    clothing_ids = [data.outfit_image_id] if data.outfit_image_id else [p.image_id for p in pieces]
    person, *clothing = get_owned_images(db, user, [data.person_image_id, *clothing_ids])

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
