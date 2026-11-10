"""Database access for notifications and notification settings. Queries only; never commits."""

import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.pagination import Cursor
from app.models.notification import Notification, NotificationSettings


def add(db: Session, instance) -> None:
    db.add(instance)
    db.flush()


def get(db: Session, notification_id: uuid.UUID) -> Notification | None:
    return db.get(Notification, notification_id)


def latest_in_group(db: Session, user_id: uuid.UUID, group_key: str) -> Notification | None:
    return db.scalar(
        select(Notification)
        .where(Notification.user_id == user_id, Notification.group_key == group_key)
        .order_by(Notification.created_at.desc())
        .limit(1)
    )


def list_newest(db: Session, user_id: uuid.UUID, *, limit: int, cursor: Cursor | None) -> list[Notification]:
    statement = select(Notification).where(Notification.user_id == user_id)
    if cursor is not None:
        statement = statement.where(
            or_(
                Notification.created_at < cursor.created_at,
                and_(Notification.created_at == cursor.created_at, Notification.id < cursor.id),
            )
        )
    statement = statement.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    return list(db.scalars(statement))


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
    )


def mark_read(db: Session, user_id: uuid.UUID, ids: list[uuid.UUID] | None, at: datetime) -> None:
    """Mark the given notifications read, or all of them when ids is None."""
    statement = update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    if ids is not None:
        statement = statement.where(Notification.id.in_(ids))
    db.execute(statement.values(read_at=at))


def get_settings(db: Session, user_id: uuid.UUID) -> NotificationSettings | None:
    return db.get(NotificationSettings, user_id)
