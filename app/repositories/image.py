"""Database access for images. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.image import Image


def get(db: Session, image_id: uuid.UUID) -> Image | None:
    return db.get(Image, image_id)


def get_many(db: Session, image_ids: list[uuid.UUID]) -> list[Image]:
    return list(db.scalars(select(Image).where(Image.id.in_(image_ids))))


def add(db: Session, image: Image) -> Image:
    db.add(image)
    db.flush()
    db.refresh(image)
    return image
