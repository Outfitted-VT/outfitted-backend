"""Likes and saves. All operations are idempotent: liking twice is the same as liking once."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.pagination import decode_cursor
from app.models.user import User
from app.repositories import engagement as engagement_repository
from app.services.fit import FitPage, get_fit, paginate


def _add_once(db: Session, exists, add, user: User, fit_id: uuid.UUID) -> None:
    get_fit(db, fit_id)  # raises FitNotFoundError
    if exists(db, user.id, fit_id):
        return
    try:
        add(db, user.id, fit_id)
        db.commit()
    except IntegrityError:
        # The same user did it twice at the same moment (e.g. a double tap); one insert won.
        db.rollback()


def like_fit(db: Session, user: User, fit_id: uuid.UUID) -> None:
    _add_once(db, engagement_repository.has_liked, engagement_repository.add_like, user, fit_id)


def unlike_fit(db: Session, user: User, fit_id: uuid.UUID) -> None:
    get_fit(db, fit_id)
    engagement_repository.remove_like(db, user.id, fit_id)
    db.commit()


def save_fit(db: Session, user: User, fit_id: uuid.UUID) -> None:
    _add_once(db, engagement_repository.has_saved, engagement_repository.add_save, user, fit_id)


def unsave_fit(db: Session, user: User, fit_id: uuid.UUID) -> None:
    get_fit(db, fit_id)
    engagement_repository.remove_save(db, user.id, fit_id)
    db.commit()


def list_saved_fits(db: Session, user: User, *, limit: int, cursor: str | None) -> FitPage:
    """Fits the user saved, most recently saved first. Raises InvalidCursorError."""
    decoded = decode_cursor(cursor) if cursor else None
    rows = engagement_repository.list_saved(db, user_id=user.id, limit=limit + 1, cursor=decoded)
    return paginate(db, user, rows, limit, lambda row: (row[1].created_at, row[1].fit_id))
