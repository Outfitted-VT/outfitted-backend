from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate


class EmailAlreadyRegisteredError(Exception):
    pass


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def create_user(db: Session, user_in: UserCreate) -> User:
    if get_user_by_email(db, user_in.email) is not None:
        raise EmailAlreadyRegisteredError

    user = User(
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        full_name=user_in.full_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Another request registered the same email between our check and the insert.
        db.rollback()
        raise EmailAlreadyRegisteredError from None
    db.refresh(user)
    return user
