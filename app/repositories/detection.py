"""Database access for image detections. Queries only: no business rules, and never commits."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.detection import ImageDetection


def get_for_image(db: Session, image_id: uuid.UUID) -> ImageDetection | None:
    return db.scalar(select(ImageDetection).where(ImageDetection.image_id == image_id))


def add(db: Session, detection: ImageDetection) -> ImageDetection:
    db.add(detection)
    db.flush()
    return detection


def count_since(db: Session, user_id: uuid.UUID, since: datetime) -> int:
    return db.scalar(
        select(func.count()).where(
            ImageDetection.user_id == user_id, ImageDetection.created_at >= since
        )
    )
