"""Fit posts: creating, editing, deleting, and listing."""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.pagination import decode_cursor, encode_cursor
from app.models.fit import Fit, FitImage, FitItem
from app.models.user import User
from app.repositories import fit as fit_repository
from app.schemas.fit import FitCreate, FitItemIn, FitUpdate
from app.services.image import get_owned_images
from app.storage import Storage


class FitNotFoundError(Exception):
    pass


class NotFitOwnerError(Exception):
    pass


class ImageAlreadyUsedError(Exception):
    pass


class InvalidItemPinError(Exception):
    pass


@dataclass(frozen=True)
class FitPage:
    fits: list[Fit]
    next_cursor: str | None


def _build_items(items: list[FitItemIn]) -> list[FitItem]:
    return [
        FitItem(
            position=position,
            category=item.category.value,
            name=item.name,
            brand=item.brand,
            color=item.color,
            url=str(item.url) if item.url else None,
            pin_image_id=item.pin.image_id if item.pin else None,
            pin_x=item.pin.x if item.pin else None,
            pin_y=item.pin.y if item.pin else None,
        )
        for position, item in enumerate(items)
    ]


def _get_visible_fit(db: Session, fit_id: uuid.UUID) -> Fit:
    fit = fit_repository.get(db, fit_id)
    if fit is None or not fit.author.is_active:
        raise FitNotFoundError
    return fit


def _get_own_fit(db: Session, editor: User, fit_id: uuid.UUID) -> Fit:
    fit = _get_visible_fit(db, fit_id)
    if fit.user_id != editor.id:
        raise NotFitOwnerError
    return fit


def create_fit(db: Session, author: User, data: FitCreate) -> Fit:
    """Raises ImageNotFoundError if an image isn't the author's, ImageAlreadyUsedError if
    an image is already in another fit."""
    images = get_owned_images(db, author, data.image_ids)
    if fit_repository.used_image_ids(db, data.image_ids):
        raise ImageAlreadyUsedError

    fit = Fit(
        user_id=author.id,
        caption=data.caption,
        fit_images=[FitImage(image=image, position=i) for i, image in enumerate(images)],
        items=_build_items(data.items),
    )
    try:
        fit_repository.add(db, fit)
        db.commit()
    except IntegrityError:
        # Another request attached one of these images to a fit at the same time.
        db.rollback()
        raise ImageAlreadyUsedError from None
    return fit_repository.get(db, fit.id)


def get_fit(db: Session, fit_id: uuid.UUID) -> Fit:
    return _get_visible_fit(db, fit_id)


def update_fit(db: Session, editor: User, fit_id: uuid.UUID, changes: FitUpdate) -> Fit:
    fit = _get_own_fit(db, editor, fit_id)
    fields = changes.model_fields_set

    if "caption" in fields:
        fit.caption = changes.caption
    if "items" in fields:
        image_ids = {image.id for image in fit.images}
        if any(item.pin and item.pin.image_id not in image_ids for item in changes.items):
            raise InvalidItemPinError
        fit.items = _build_items(changes.items)

    db.commit()
    return fit_repository.get(db, fit.id)


def delete_fit(db: Session, storage: Storage, editor: User, fit_id: uuid.UUID) -> None:
    """Delete the fit and its photos, except a photo also used as the editor's avatar."""
    fit = _get_own_fit(db, editor, fit_id)
    images = [image for image in fit.images if image.id != editor.avatar_image_id]

    fit_repository.delete(db, fit)
    for image in images:
        db.delete(image)
    db.commit()
    # Remove files only after the database commit, so a failed commit doesn't lose photos.
    for image in images:
        storage.delete(image.storage_key)


def list_fits(
    db: Session, *, limit: int, cursor: str | None, author: User | None = None
) -> FitPage:
    """Newest fits first, optionally by one author. Raises InvalidCursorError."""
    decoded = decode_cursor(cursor) if cursor else None
    # Fetch one extra row to know whether there's another page.
    fits = fit_repository.list_newest(
        db, limit=limit + 1, cursor=decoded, user_id=author.id if author else None
    )
    if len(fits) <= limit:
        return FitPage(fits=fits, next_cursor=None)
    fits = fits[:limit]
    last = fits[-1]
    return FitPage(fits=fits, next_cursor=encode_cursor(last.created_at, last.id))
