"""Image uploads: validation, storage, and ownership."""

import uuid

from sqlalchemy.orm import Session

from app.core.images import (
    OUTPUT_CONTENT_TYPE,
    OUTPUT_EXTENSION,
    ProcessedImage,
    blur_regions,
    process_image,
    to_jpeg,
)
from app.faces import FaceLocator
from app.models.image import Image
from app.models.user import User
from app.repositories import image as image_repository
from app.storage import Storage


class ImageNotFoundError(Exception):
    """The image doesn't exist or belongs to someone else."""


class NoFaceFoundError(Exception):
    """The model found no face to blur in the image."""


def _store(
    db: Session, storage: Storage, owner: User, processed: ProcessedImage, *, generated: bool
) -> Image:
    key = f"images/{uuid.uuid4().hex}.{OUTPUT_EXTENSION}"
    storage.save(key, processed.data, OUTPUT_CONTENT_TYPE)
    image = Image(
        owner_id=owner.id,
        storage_key=key,
        width=processed.width,
        height=processed.height,
        size_bytes=len(processed.data),
        generated=generated,
    )
    try:
        image_repository.add(db, image)
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(key)
        raise
    return image


def upload_image(
    db: Session, storage: Storage, owner: User, data: bytes, *, generated: bool = False
) -> Image:
    """Validate, re-encode, and store an upload. Raises InvalidImageError for bad files."""
    return _store(db, storage, owner, process_image(data), generated=generated)


def get_owned_images(db: Session, owner: User, image_ids: list[uuid.UUID]) -> list[Image]:
    """Load images in the given order, ensuring the owner uploaded every one of them."""
    images = {image.id: image for image in image_repository.get_many(db, image_ids)}
    if any(images.get(i) is None or images[i].owner_id != owner.id for i in image_ids):
        raise ImageNotFoundError
    return [images[i] for i in image_ids]


def blur_faces(
    db: Session, storage: Storage, locator: FaceLocator, owner: User, image_id: uuid.UUID
) -> Image:
    """Store a copy of one of the owner's images with every face blurred. The original is kept.

    The copy keeps the original's `generated` flag, so a blurred try-on is still labeled AI.
    Raises ImageNotFoundError, NoFaceFoundError, and FaceLocatorUnavailableError.
    """
    [image] = get_owned_images(db, owner, [image_id])
    data = storage.read(image.storage_key)
    boxes = locator.locate(to_jpeg(data))
    if not boxes:
        raise NoFaceFoundError
    return _store(db, storage, owner, blur_regions(data, boxes), generated=image.generated)
