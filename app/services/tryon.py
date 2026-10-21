"""Virtual try-on: put the outfit from one of your photos onto a photo of yourself."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.images import InvalidImageError, to_jpeg
from app.models.tryon import TryOn
from app.models.user import User
from app.repositories import tryon as tryon_repository
from app.services.image import get_owned_images, upload_image
from app.storage import Storage
from app.tryon import TryOnBlockedError, TryOnGenerator


class DailyLimitReachedError(Exception):
    pass


def create_tryon(
    db: Session,
    storage: Storage,
    generator: TryOnGenerator,
    user: User,
    person_image_id: uuid.UUID,
    outfit_image_id: uuid.UUID,
) -> TryOn:
    """Generate the try-on and store the result as a new image the user owns.

    Raises ImageNotFoundError if either image isn't the user's, DailyLimitReachedError, and
    TryOnError from the generator.
    """
    person, outfit = get_owned_images(db, user, [person_image_id, outfit_image_id])

    since = datetime.now(UTC) - timedelta(days=1)
    if tryon_repository.count_since(db, user.id, since) >= settings.TRYON_DAILY_LIMIT:
        raise DailyLimitReachedError

    result = generator.generate(
        to_jpeg(storage.read(person.storage_key)), to_jpeg(storage.read(outfit.storage_key))
    )
    try:
        # Re-encoded like any upload: WebP, at most 2048px, metadata stripped.
        result_image = upload_image(db, storage, user, result, generated=True)
    except InvalidImageError:
        raise TryOnBlockedError("We couldn't create a try-on from these photos") from None

    tryon = TryOn(
        user_id=user.id,
        person_image_id=person.id,
        outfit_image_id=outfit.id,
        result_image_id=result_image.id,
        model=settings.TRYON_MODEL,
    )
    tryon_repository.add(db, tryon)
    db.commit()
    return tryon
