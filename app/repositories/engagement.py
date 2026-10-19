"""Database access for likes and saves. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import Cursor
from app.models.engagement import FitLike, FitSave
from app.models.fit import Fit
from app.models.user import User
from app.repositories.fit import with_details


def add_like(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID) -> None:
    """Raises IntegrityError if the like already exists."""
    db.add(FitLike(user_id=user_id, fit_id=fit_id))
    db.flush()


def remove_like(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID) -> None:
    db.execute(delete(FitLike).where(FitLike.user_id == user_id, FitLike.fit_id == fit_id))


def has_liked(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID) -> bool:
    return db.get(FitLike, (user_id, fit_id)) is not None


def add_save(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID) -> None:
    """Raises IntegrityError if the save already exists."""
    db.add(FitSave(user_id=user_id, fit_id=fit_id))
    db.flush()


def remove_save(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID) -> None:
    db.execute(delete(FitSave).where(FitSave.user_id == user_id, FitSave.fit_id == fit_id))


def has_saved(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID) -> bool:
    return db.get(FitSave, (user_id, fit_id)) is not None


def like_counts(db: Session, fit_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(FitLike.fit_id, func.count())
        .where(FitLike.fit_id.in_(fit_ids))
        .group_by(FitLike.fit_id)
    )
    return {fit_id: count for fit_id, count in rows}


def liked_fit_ids(db: Session, user_id: uuid.UUID, fit_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(FitLike.fit_id).where(FitLike.user_id == user_id, FitLike.fit_id.in_(fit_ids))
        )
    )


def saved_fit_ids(db: Session, user_id: uuid.UUID, fit_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(FitSave.fit_id).where(FitSave.user_id == user_id, FitSave.fit_id.in_(fit_ids))
        )
    )


def list_saved(
    db: Session, *, user_id: uuid.UUID, limit: int, cursor: Cursor | None
) -> list[tuple[Fit, FitSave]]:
    """A user's saved fits by active authors, most recently saved first.

    The cursor is the (saved_at, fit_id) of the last row.
    """
    statement = (
        select(Fit, FitSave)
        .join(FitSave, FitSave.fit_id == Fit.id)
        .join(Fit.author)
        .where(FitSave.user_id == user_id, User.is_active)
    )
    if cursor is not None:
        statement = statement.where(
            or_(
                FitSave.created_at < cursor.created_at,
                and_(FitSave.created_at == cursor.created_at, FitSave.fit_id < cursor.id),
            )
        )
    statement = statement.order_by(FitSave.created_at.desc(), FitSave.fit_id.desc()).limit(limit)
    return [tuple(row) for row in db.execute(with_details(statement))]
