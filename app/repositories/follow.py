"""Database access for follows and profile counts. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import Cursor
from app.models.fit import Fit
from app.models.follow import Follow
from app.models.user import User


def add(db: Session, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
    """Raises IntegrityError if the follow already exists."""
    db.add(Follow(follower_id=follower_id, followee_id=followee_id))
    db.flush()


def remove(db: Session, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
    db.execute(
        delete(Follow).where(Follow.follower_id == follower_id, Follow.followee_id == followee_id)
    )


def exists(db: Session, follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
    return db.get(Follow, (follower_id, followee_id)) is not None


def _count(db: Session, statement) -> int:
    return db.scalar(select(func.count()).select_from(statement.subquery()))


def follower_count(db: Session, user_id: uuid.UUID) -> int:
    """Active users following this user."""
    return _count(
        db,
        select(Follow.follower_id)
        .join(User, User.id == Follow.follower_id)
        .where(Follow.followee_id == user_id, User.is_active),
    )


def following_count(db: Session, user_id: uuid.UUID) -> int:
    """Active users this user follows."""
    return _count(
        db,
        select(Follow.followee_id)
        .join(User, User.id == Follow.followee_id)
        .where(Follow.follower_id == user_id, User.is_active),
    )


def fit_count(db: Session, user_id: uuid.UUID) -> int:
    return _count(db, select(Fit.id).where(Fit.user_id == user_id))


def followee_ids(follower_id: uuid.UUID):
    """Subquery of the ids a user follows, for use in other queries."""
    return select(Follow.followee_id).where(Follow.follower_id == follower_id)


def _list_users(
    db: Session, *, user_column, filter_column, user_id: uuid.UUID, limit: int, cursor: Cursor | None
) -> list[tuple[User, Follow]]:
    statement = (
        select(User, Follow)
        .join(Follow, user_column == User.id)
        .where(filter_column == user_id, User.is_active)
    )
    if cursor is not None:
        statement = statement.where(
            or_(
                Follow.created_at < cursor.created_at,
                and_(Follow.created_at == cursor.created_at, User.id < cursor.id),
            )
        )
    statement = statement.order_by(Follow.created_at.desc(), User.id.desc()).limit(limit)
    return [tuple(row) for row in db.execute(statement)]


def list_followers(
    db: Session, *, user_id: uuid.UUID, limit: int, cursor: Cursor | None
) -> list[tuple[User, Follow]]:
    """Active users following `user_id`, most recent first. Cursor is (followed_at, user id)."""
    return _list_users(
        db,
        user_column=Follow.follower_id,
        filter_column=Follow.followee_id,
        user_id=user_id,
        limit=limit,
        cursor=cursor,
    )


def list_following(
    db: Session, *, user_id: uuid.UUID, limit: int, cursor: Cursor | None
) -> list[tuple[User, Follow]]:
    """Active users `user_id` follows, most recent first. Cursor is (followed_at, user id)."""
    return _list_users(
        db,
        user_column=Follow.followee_id,
        filter_column=Follow.follower_id,
        user_id=user_id,
        limit=limit,
        cursor=cursor,
    )
