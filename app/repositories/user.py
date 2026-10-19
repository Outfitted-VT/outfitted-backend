"""Database access for users. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import select
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
