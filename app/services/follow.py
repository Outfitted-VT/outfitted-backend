"""Follows, profiles with counts, and the following feed."""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.pagination import decode_cursor, encode_cursor
from app.models.user import User
from app.repositories import fit as fit_repository
from app.repositories import follow as follow_repository
from app.services.fit import FitPage, paginate
from app.services.user import get_user_by_username


class UserNotFoundError(Exception):
    pass


class CannotFollowSelfError(Exception):
    pass


@dataclass(frozen=True)
class ProfileView:
    user: User
    fit_count: int
    follower_count: int
    following_count: int
    is_following: bool


@dataclass(frozen=True)
class UserPage:
    users: list[User]
    next_cursor: str | None


def _get_user(db: Session, username: str) -> User:
    user = get_user_by_username(db, username)
    if user is None:
        raise UserNotFoundError
    return user


def get_profile(db: Session, viewer: User, username: str) -> ProfileView:
    user = _get_user(db, username)
    return ProfileView(
        user=user,
        fit_count=follow_repository.fit_count(db, user.id),
        follower_count=follow_repository.follower_count(db, user.id),
        following_count=follow_repository.following_count(db, user.id),
        is_following=follow_repository.exists(db, viewer.id, user.id),
    )


def follow(db: Session, follower: User, username: str) -> None:
    """Idempotent. Raises UserNotFoundError or CannotFollowSelfError."""
    followee = _get_user(db, username)
    if followee.id == follower.id:
        raise CannotFollowSelfError
    if follow_repository.exists(db, follower.id, followee.id):
        return
    try:
        follow_repository.add(db, follower.id, followee.id)
        db.commit()
    except IntegrityError:
        # A concurrent duplicate request already created the follow.
        db.rollback()


def unfollow(db: Session, follower: User, username: str) -> None:
    """Idempotent. Raises UserNotFoundError."""
    followee = _get_user(db, username)
    follow_repository.remove(db, follower.id, followee.id)
    db.commit()


def _user_page(rows: list, limit: int) -> UserPage:
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more:
        user, follow_row = rows[-1]
        next_cursor = encode_cursor(follow_row.created_at, user.id)
    return UserPage(users=[user for user, _ in rows], next_cursor=next_cursor)


def list_followers(db: Session, username: str, *, limit: int, cursor: str | None) -> UserPage:
    """Raises UserNotFoundError or InvalidCursorError."""
    user = _get_user(db, username)
    decoded = decode_cursor(cursor) if cursor else None
    rows = follow_repository.list_followers(db, user_id=user.id, limit=limit + 1, cursor=decoded)
    return _user_page(rows, limit)


def list_following(db: Session, username: str, *, limit: int, cursor: str | None) -> UserPage:
    """Raises UserNotFoundError or InvalidCursorError."""
    user = _get_user(db, username)
    decoded = decode_cursor(cursor) if cursor else None
    rows = follow_repository.list_following(db, user_id=user.id, limit=limit + 1, cursor=decoded)
    return _user_page(rows, limit)


def following_feed(db: Session, viewer: User, *, limit: int, cursor: str | None) -> FitPage:
    """Fits from people the viewer follows, plus their own, newest first."""
    decoded = decode_cursor(cursor) if cursor else None
    fits = fit_repository.list_newest(
        db,
        limit=limit + 1,
        cursor=decoded,
        user_ids=follow_repository.followee_ids(viewer.id),
        include_user_id=viewer.id,
    )
    return paginate(db, viewer, fits, limit, lambda fit: (fit.created_at, fit.id))
