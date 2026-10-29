"""Database access for users. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

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
) -> list[User]:
    stmt = select(User).where(User.is_active.is_(True))
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)

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
