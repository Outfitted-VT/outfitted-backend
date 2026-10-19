"""User business rules. Uses the user repository for data access and owns commit/rollback."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories import user as user_repository
from app.schemas.user import UserCreate


class EmailAlreadyRegisteredError(Exception):
    pass


def get_user(db: Session, user_id: uuid.UUID) -> User | None:
    return user_repository.get(db, user_id)


def create_user(db: Session, user_in: UserCreate) -> User:
    if user_repository.get_by_email(db, user_in.email) is not None:
        raise EmailAlreadyRegisteredError

    user = User(
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        full_name=user_in.full_name,
    )
    try:
        user_repository.add(db, user)
        db.commit()
    except IntegrityError:
        # Another request registered the same email between our check and the insert.
        db.rollback()
        raise EmailAlreadyRegisteredError from None
    return user


# Verified against when the email doesn't exist, so a login attempt takes the same time
# whether or not the account exists (otherwise response timing reveals registered emails).
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = user_repository.get_by_email(db, email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
