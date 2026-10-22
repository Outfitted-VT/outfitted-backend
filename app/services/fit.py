"""Fit posts: creating, editing, deleting, and listing."""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.pagination import decode_cursor, encode_cursor
from app.models.fit import Fit, FitImage, FitItem, FitTag
from app.models.user import User
from app.repositories import engagement as engagement_repository
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
class FitView:
    """A fit as seen by a particular viewer."""

    fit: Fit
    like_count: int
    liked_by_me: bool
    saved_by_me: bool


@dataclass(frozen=True)
class FitPage:
    views: list[FitView]
    next_cursor: str | None


def describe_fits(db: Session, viewer: User, fits: list[Fit]) -> list[FitView]:
    """Attach like counts and the viewer's likes/saves, in three queries for the whole list."""
    fit_ids = [fit.id for fit in fits]
    if not fit_ids:
        return []
    counts = engagement_repository.like_counts(db, fit_ids)
    liked = engagement_repository.liked_fit_ids(db, viewer.id, fit_ids)
    saved = engagement_repository.saved_fit_ids(db, viewer.id, fit_ids)
    return [
        FitView(
            fit=fit,
            like_count=counts.get(fit.id, 0),
            liked_by_me=fit.id in liked,
            saved_by_me=fit.id in saved,
        )
        for fit in fits
    ]


def describe_fit(db: Session, viewer: User, fit: Fit) -> FitView:
    return describe_fits(db, viewer, [fit])[0]


def paginate(db: Session, viewer: User, rows: list, limit: int, cursor_of) -> FitPage:
    """Turn `limit + 1` fetched rows into a page. `cursor_of(row)` gives (created_at, id)
    and each row is a Fit or a (Fit, ...) tuple."""
    has_more = len(rows) > limit
    rows = rows[:limit]
    fits = [row[0] if isinstance(row, tuple) else row for row in rows]
    next_cursor = encode_cursor(*cursor_of(rows[-1])) if has_more else None
    return FitPage(views=describe_fits(db, viewer, fits), next_cursor=next_cursor)


def _build_items(items: list[FitItemIn]) -> list[FitItem]:
    return [
        FitItem(
            position=position,
            category=item.category.value,
            name=item.name,
            brand=item.brand,
            color=item.color,
            pattern=item.pattern,
            material=item.material,
            silhouette=item.silhouette,
            url=str(item.url) if item.url else None,
            pin_image_id=item.pin.image_id if item.pin else None,
            pin_x=item.pin.x if item.pin else None,
            pin_y=item.pin.y if item.pin else None,
            source=item.source,
        )
        for position, item in enumerate(items)
    ]


def _build_tags(occasion_tags: list[str], style_tags: list[str]) -> list[FitTag]:
    return [
        FitTag(kind=kind, tag=tag, position=position)
        for kind, tags in (("occasion", occasion_tags), ("style", style_tags))
        for position, tag in enumerate(tags)
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
        tags=_build_tags(data.occasion_tags, data.style_tags),
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
    if fields & {"occasion_tags", "style_tags"}:
        occasion = changes.occasion_tags if "occasion_tags" in fields else fit.occasion_tags
        style = changes.style_tags if "style_tags" in fields else fit.style_tags
        # Flush the removal first: the new rows can reuse the same (fit, kind, tag) keys.
        fit.tags = []
        db.flush()
        fit.tags = _build_tags(occasion, style)

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
    db: Session, viewer: User, *, limit: int, cursor: str | None, author: User | None = None
) -> FitPage:
    """Newest fits first, optionally by one author. Raises InvalidCursorError."""
    decoded = decode_cursor(cursor) if cursor else None
    # Fetch one extra row to know whether there's another page.
    fits = fit_repository.list_newest(
        db, limit=limit + 1, cursor=decoded, user_id=author.id if author else None
    )
    return paginate(db, viewer, fits, limit, lambda fit: (fit.created_at, fit.id))
