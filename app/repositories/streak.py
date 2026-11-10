"""Database access for streaks. Queries only; never commits."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.streak import UserStreak
from app.models.user import User


def get(db: Session, user_id: uuid.UUID) -> UserStreak | None:
    return db.get(UserStreak, user_id)


def add(db: Session, streak: UserStreak) -> None:
    """Raises IntegrityError if the user already has a streak row."""
    db.add(streak)
    db.flush()


def get_many(db: Session, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, UserStreak]:
    if not user_ids:
        return {}
    return {s.user_id: s for s in db.scalars(select(UserStreak).where(UserStreak.user_id.in_(user_ids)))}


def running(db: Session, *, at_least: int = 1) -> list[tuple[UserStreak, User]]:
    """Streaks of active users with a current count of at least `at_least`."""
    rows = db.execute(
        select(UserStreak, User)
        .join(User, User.id == UserStreak.user_id)
        .where(UserStreak.current_count >= at_least, User.is_active.is_(True))
    )
    return [tuple(row) for row in rows]
