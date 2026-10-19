"""User business rules. Uses the user repository for data access and owns commit/rollback."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories import user as user_repository
from app.schemas.user import UserCreate, UserUpdate
from app.services.image import get_owned_images


class EmailAlreadyRegisteredError(Exception):
    pass


class UsernameTakenError(Exception):
    pass


def get_user(db: Session, user_id: uuid.UUID) -> User | None:
    return user_repository.get(db, user_id)


def get_user_by_username(db: Session, username: str) -> User | None:
    user = user_repository.get_by_username(db, username)
    return user if user is not None and user.is_active else None


def _conflict_error(error: IntegrityError) -> Exception:
    # Another request took the same email or username between our check and the write.
    if "username" in str(error.orig).lower():
        return UsernameTakenError()
    return EmailAlreadyRegisteredError()


def create_user(db: Session, user_in: UserCreate) -> User:
    if user_repository.get_by_email(db, user_in.email) is not None:
        raise EmailAlreadyRegisteredError
    if user_repository.get_by_username(db, user_in.username) is not None:
        raise UsernameTakenError

    user = User(
        email=user_in.email,
        username=user_in.username,
        hashed_password=hash_password(user_in.password),
        full_name=user_in.full_name,
    )
    try:
        user_repository.add(db, user)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise _conflict_error(error) from None
    return user


def update_profile(db: Session, user: User, changes: UserUpdate) -> User:
    """Apply only the fields the client sent. Raises ImageNotFoundError for a foreign avatar."""
    fields = changes.model_fields_set

    if "username" in fields and changes.username != user.username:
        existing = user_repository.get_by_username(db, changes.username)
        if existing is not None:
            raise UsernameTakenError
        user.username = changes.username
    if "full_name" in fields:
        user.full_name = changes.full_name
    if "bio" in fields:
        user.bio = changes.bio
    if "avatar_image_id" in fields:
        if changes.avatar_image_id is None:
            user.avatar = None
        else:
            [user.avatar] = get_owned_images(db, user, [changes.avatar_image_id])

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise _conflict_error(error) from None
    db.refresh(user)
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
