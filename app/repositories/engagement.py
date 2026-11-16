"""Database access for likes and saves. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import Cursor
from app.models.engagement import FitLike, FitSave, SavedPiece
from app.models.fit import Fit
from app.models.tryon import TryOn
from app.models.user import User
from app.repositories.fit import visible_to, with_details


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


def save_counts(db: Session, fit_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(FitSave.fit_id, func.count())
        .where(FitSave.fit_id.in_(fit_ids))
        .group_by(FitSave.fit_id)
    )
    return {fit_id: count for fit_id, count in rows}


def tried_counts(db: Session, fit_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """How many people tried each fit on with "Try this look": distinct users, not counting
    the fit's author."""
    rows = db.execute(
        select(TryOn.source_fit_id, func.count(func.distinct(TryOn.user_id)))
        .join(Fit, Fit.id == TryOn.source_fit_id)
        .where(TryOn.source_fit_id.in_(fit_ids), TryOn.user_id != Fit.user_id)
        .group_by(TryOn.source_fit_id)
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
        .where(FitSave.user_id == user_id, User.is_active, visible_to(user_id))
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


# --- Saved pieces ---------------------------------------------------------------------------


def piece_key(category: str, name: str) -> tuple[str, str]:
    """How a saved piece matches a fit's item: same category and name (case-insensitive)."""
    return category, name.strip().lower()


def find_saved_piece(
    db: Session, user_id: uuid.UUID, fit_id: uuid.UUID, category: str, name: str
) -> SavedPiece | None:
    for piece in db.scalars(
        select(SavedPiece).where(
            SavedPiece.user_id == user_id, SavedPiece.fit_id == fit_id, SavedPiece.category == category
        )
    ):
        if piece_key(piece.category, piece.name) == piece_key(category, name):
            return piece
    return None


def add_saved_piece(db: Session, piece: SavedPiece) -> SavedPiece:
    db.add(piece)
    db.flush()
    return piece


def get_saved_piece(db: Session, user_id: uuid.UUID, piece_id: uuid.UUID) -> SavedPiece | None:
    piece = db.get(SavedPiece, piece_id)
    return piece if piece is not None and piece.user_id == user_id else None


def delete_saved_piece(db: Session, piece: SavedPiece) -> None:
    db.delete(piece)


def saved_piece_ids(
    db: Session, user_id: uuid.UUID, fit_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[tuple[str, str], uuid.UUID]]:
    """For each fit, the viewer's saved pieces from it: {fit_id: {(category, name): piece_id}}."""
    result: dict[uuid.UUID, dict[tuple[str, str], uuid.UUID]] = {}
    rows = db.execute(
        select(SavedPiece.fit_id, SavedPiece.category, SavedPiece.name, SavedPiece.id).where(
            SavedPiece.user_id == user_id, SavedPiece.fit_id.in_(fit_ids)
        )
    )
    for fit_id, category, name, piece_id in rows:
        result.setdefault(fit_id, {})[piece_key(category, name)] = piece_id
    return result


def list_saved_pieces(
    db: Session, *, user_id: uuid.UUID, limit: int, cursor: Cursor | None
) -> list[SavedPiece]:
    """A user's saved pieces, most recently saved first. The cursor is (created_at, id)."""
    statement = select(SavedPiece).where(SavedPiece.user_id == user_id)
    if cursor is not None:
        statement = statement.where(
            or_(
                SavedPiece.created_at < cursor.created_at,
                and_(SavedPiece.created_at == cursor.created_at, SavedPiece.id < cursor.id),
            )
        )
    statement = statement.order_by(SavedPiece.created_at.desc(), SavedPiece.id.desc()).limit(limit)
    return list(db.scalars(statement))
