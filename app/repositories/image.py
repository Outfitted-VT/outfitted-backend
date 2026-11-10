"""Database access for images. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import String, cast, or_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session

from app.models.conversation import Message
from app.models.detection import ImageDetection
from app.models.fit import FitImage, FitItem
from app.models.image import Image
from app.models.story import Story
from app.models.tryon import TryOn, TryOnPiece
from app.models.user import User
from app.models.wardrobe import WardrobeItem


def get(db: Session, image_id: uuid.UUID) -> Image | None:
    return db.get(Image, image_id)


def get_many(db: Session, image_ids: list[uuid.UUID]) -> list[Image]:
    return list(db.scalars(select(Image).where(Image.id.in_(image_ids))))


def add(db: Session, image: Image) -> Image:
    db.add(image)
    db.flush()
    db.refresh(image)
    return image


def _references(image: Image) -> list:
    return [
        select(User.id).where(User.avatar_image_id == image.id),
        select(FitImage.fit_id).where(FitImage.image_id == image.id),
        select(FitItem.id).where(FitItem.pin_image_id == image.id),
        select(TryOn.id).where(
            or_(TryOn.person_image_id == image.id, TryOn.outfit_image_id == image.id, TryOn.result_image_id == image.id)
        ),
        select(TryOnPiece.image_id).where(TryOnPiece.image_id == image.id),
        select(Story.id).where(Story.image_id == image.id),
        select(Message.id).where(Message.kind != "story_reply", cast(Message.payload, String).contains(str(image.id))),
        select(WardrobeItem.id).where(WardrobeItem.image_url.contains(image.storage_key)),
    ]


def is_in_use(db: Session, image: Image) -> bool:
    """Whether anything other than a story reply's thumbnail still points at the image."""
    return any(db.scalar(statement.limit(1)) is not None for statement in _references(image))


def delete(db: Session, image: Image) -> None:
    db.execute(sa_delete(ImageDetection).where(ImageDetection.image_id == image.id))
    db.delete(image)
    db.flush()
