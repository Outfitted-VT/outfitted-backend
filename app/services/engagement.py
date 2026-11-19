"""Likes and saves. All operations are idempotent: liking twice is the same as liking once."""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.pagination import decode_cursor, encode_cursor
from app.models.engagement import SavedPiece
from app.models.user import User
from app.repositories import engagement as engagement_repository
from app.services import notification as notifications
from app.services.fit import FitPage, get_fit, paginate


def _add_once(db: Session, exists, add, user: User, fit_id: uuid.UUID) -> bool:
    """True when this call added it."""
    get_fit(db, fit_id, user)  # raises FitNotFoundError
    if exists(db, user.id, fit_id):
        return False
    try:
        add(db, user.id, fit_id)
        db.commit()
    except IntegrityError:
        # The same user did it twice at the same moment (e.g. a double tap); one insert won.
        db.rollback()
        return False
    return True


def like_fit(db: Session, user: User, fit_id: uuid.UUID) -> None:
    if _add_once(db, engagement_repository.has_liked, engagement_repository.add_like, user, fit_id):
        fit = get_fit(db, fit_id, user)
        notifications.notify(db, fit.user_id, "like", actor=user, entity_type="fit", entity_id=fit.id)


def unlike_fit(db: Session, user: User, fit_id: uuid.UUID) -> None:
    get_fit(db, fit_id, user)
    engagement_repository.remove_like(db, user.id, fit_id)
    db.commit()


def save_fit(db: Session, user: User, fit_id: uuid.UUID) -> None:
    _add_once(db, engagement_repository.has_saved, engagement_repository.add_save, user, fit_id)


def unsave_fit(db: Session, user: User, fit_id: uuid.UUID) -> None:
    get_fit(db, fit_id, user)
    engagement_repository.remove_save(db, user.id, fit_id)
    db.commit()


def list_saved_fits(db: Session, user: User, *, limit: int, cursor: str | None) -> FitPage:
    """Fits the user saved, most recently saved first. Raises InvalidCursorError."""
    decoded = decode_cursor(cursor) if cursor else None
    rows = engagement_repository.list_saved(db, user_id=user.id, limit=limit + 1, cursor=decoded)
    return paginate(db, user, rows, limit, lambda row: (row[1].created_at, row[1].fit_id))


# --- Saved pieces ---------------------------------------------------------------------------


class FitItemNotFoundError(Exception):
    pass


class SavedPieceNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class SavedPiecePage:
    pieces: list[SavedPiece]
    next_cursor: str | None


def photo_for(fit, item, index: int):
    """The fit photo a piece is on, and whether several pieces share it (then zoom on the pin).
    Same rule the app uses to draw a piece (crop() in the frontend's fit-card.js). A piece with
    its own photo (a try-on's clothing photo) uses that, whole."""
    if item.image is not None:
        return item.image, False
    images = fit.images
    image = next((img for img in images if img.id == item.pin_image_id), None)
    if image is None and images:
        image = images[index] if index < len(images) else images[0]
    shared = item.pin_image_id is not None and sum(
        1 for other in fit.items if other.pin_image_id == item.pin_image_id
    ) > 1
    return image, shared


def save_piece(db: Session, user: User, fit_id: uuid.UUID, item_id: uuid.UUID) -> SavedPiece:
    """Save one piece of a fit the user can see. Idempotent: saving the same piece (same fit,
    category and name) again returns the existing save. Raises FitNotFoundError or
    FitItemNotFoundError."""
    fit = get_fit(db, fit_id, user)
    index, item = next(((i, it) for i, it in enumerate(fit.items) if it.id == item_id), (None, None))
    if item is None:
        raise FitItemNotFoundError
    existing = engagement_repository.find_saved_piece(db, user.id, fit.id, item.category, item.name)
    if existing is not None:
        return existing
    image, zoom = photo_for(fit, item, index)
    piece = SavedPiece(
        user_id=user.id,
        fit_id=fit.id,
        source_username=fit.author.username,
        category=item.category,
        name=item.name,
        brand=item.brand,
        color=item.color,
        url=item.url,
        image_id=image.id if image else None,
        pin_x=item.pin_x if zoom else None,
        pin_y=item.pin_y if zoom else None,
        zoom=zoom,
    )
    engagement_repository.add_saved_piece(db, piece)
    db.commit()
    db.refresh(piece)
    return piece


def unsave_piece(db: Session, user: User, piece_id: uuid.UUID) -> None:
    """Raises SavedPieceNotFoundError (also for someone else's piece)."""
    piece = engagement_repository.get_saved_piece(db, user.id, piece_id)
    if piece is None:
        raise SavedPieceNotFoundError
    engagement_repository.delete_saved_piece(db, piece)
    db.commit()


def list_saved_pieces(db: Session, user: User, *, limit: int, cursor: str | None) -> SavedPiecePage:
    """Raises InvalidCursorError."""
    decoded = decode_cursor(cursor) if cursor else None
    rows = engagement_repository.list_saved_pieces(db, user_id=user.id, limit=limit + 1, cursor=decoded)
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    return SavedPiecePage(pieces=rows, next_cursor=next_cursor)
