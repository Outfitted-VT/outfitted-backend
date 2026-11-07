"""Database access for users. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.follow import Follow
from app.models.user import User


def get(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username.lower()))


def add(db: Session, user: User) -> User:
    """Insert the user and load database-generated fields (e.g. created_at).

    Raises IntegrityError if a unique constraint is violated. The caller commits.
    """
    db.add(user)
    db.flush()
    db.refresh(user)
    return user


def search(
    db: Session,
    query: str = "",
    *,
    exclude_user_id: uuid.UUID | None = None,
    limit: int = 20,
    within_circle_of: uuid.UUID | None = None,
) -> list[User]:
    stmt = select(User).where(User.is_active.is_(True))
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    if within_circle_of is not None:
        stmt = stmt.where(User.id.in_(circle_ids(within_circle_of)))

    q = query.strip().lower()
    if q:
        term = f"%{q}%"
        stmt = stmt.where(
            or_(
                func.lower(User.username).like(term),
                func.lower(User.full_name).like(term),
            )
        )

    stmt = stmt.order_by(User.username).limit(limit)
    return list(db.scalars(stmt).all())


def circle_ids(user_id: uuid.UUID):
    """Subquery of the ids in a user's circle: people they follow or who follow them."""
    following = select(Follow.followee_id).where(Follow.follower_id == user_id)
    followers = select(Follow.follower_id).where(Follow.followee_id == user_id)
    return following.union(followers)


def suggestions(db: Session, user_id: uuid.UUID, *, limit: int) -> list[tuple[User, int]]:
    """Active users this user doesn't follow, with how many of their followees follow each one."""
    my_followees = select(Follow.followee_id).where(Follow.follower_id == user_id)
    mutuals = (
        select(func.count())
        .select_from(Follow)
        .where(Follow.followee_id == User.id, Follow.follower_id.in_(my_followees))
        .correlate(User)
        .scalar_subquery()
    )
    followers = (
        select(func.count())
        .select_from(Follow)
        .where(Follow.followee_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    stmt = (
        select(User, mutuals)
        .where(User.is_active.is_(True), User.id != user_id, User.id.not_in(my_followees))
        .order_by(mutuals.desc(), followers.desc(), User.username)
        .limit(limit)
    )
    return [(user, count) for user, count in db.execute(stmt)]
