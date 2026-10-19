"""Image uploads: validation, storage, and ownership."""

import uuid

from sqlalchemy.orm import Session

from app.core.images import OUTPUT_CONTENT_TYPE, OUTPUT_EXTENSION, process_image
from app.models.image import Image
from app.models.user import User
from app.repositories import image as image_repository
from app.storage import Storage


class ImageNotFoundError(Exception):
    """The image doesn't exist or belongs to someone else."""


def upload_image(db: Session, storage: Storage, owner: User, data: bytes) -> Image:
    """Validate, re-encode, and store an upload. Raises InvalidImageError for bad files."""
    processed = process_image(data)
    key = f"images/{uuid.uuid4().hex}.{OUTPUT_EXTENSION}"
    storage.save(key, processed.data, OUTPUT_CONTENT_TYPE)
    image = Image(
        owner_id=owner.id,
        storage_key=key,
        width=processed.width,
        height=processed.height,
        size_bytes=len(processed.data),
    )
    try:
        image_repository.add(db, image)
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(key)
        raise
    return image


def get_owned_images(db: Session, owner: User, image_ids: list[uuid.UUID]) -> list[Image]:
    """Load images in the given order, ensuring the owner uploaded every one of them."""
    images = {image.id: image for image in image_repository.get_many(db, image_ids)}
    if any(images.get(i) is None or images[i].owner_id != owner.id for i in image_ids):
        raise ImageNotFoundError
    return [images[i] for i in image_ids]
