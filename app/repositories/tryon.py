"""Database access for try-ons. Queries only: no business rules, and never commits."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.tryon import TryOn


def add(db: Session, tryon: TryOn) -> TryOn:
    db.add(tryon)
    db.flush()
    return tryon


def count_since(db: Session, user_id: uuid.UUID, since: datetime) -> int:
    return db.scalar(
        select(func.count()).where(TryOn.user_id == user_id, TryOn.created_at >= since)
    )
