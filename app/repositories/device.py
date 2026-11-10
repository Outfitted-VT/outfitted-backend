"""Database access for push device tokens. Queries only; never commits."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.device import DeviceToken


def get_by_token(db: Session, token: str) -> DeviceToken | None:
    return db.scalar(select(DeviceToken).where(DeviceToken.token == token))


def add(db: Session, device: DeviceToken) -> None:
    """Raises IntegrityError if the token is already registered."""
    db.add(device)
    db.flush()


def for_user(db: Session, user_id: uuid.UUID) -> list[DeviceToken]:
    return list(db.scalars(select(DeviceToken).where(DeviceToken.user_id == user_id)))


def remove(db: Session, token: str, user_id: uuid.UUID | None = None) -> None:
    statement = delete(DeviceToken).where(DeviceToken.token == token)
    if user_id is not None:
        statement = statement.where(DeviceToken.user_id == user_id)
    db.execute(statement)
