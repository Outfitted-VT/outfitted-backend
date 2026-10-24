"""Database access for fits. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.pagination import Cursor
from app.models.fit import Fit, FitImage
from app.models.user import User


def with_details(statement: Select) -> Select:
    # Load everything a FitRead needs up front, avoiding one query per fit (N+1).
    return statement.options(
        selectinload(Fit.author),
        selectinload(Fit.fit_images),
        selectinload(Fit.items),
        selectinload(Fit.tags),
    )


def get(db: Session, fit_id: uuid.UUID) -> Fit | None:
    return db.scalar(
        with_details(select(Fit).where(Fit.id == fit_id)).execution_options(populate_existing=True)
    )


def add(db: Session, fit: Fit) -> Fit:
    db.add(fit)
    db.flush()
    return fit


def delete(db: Session, fit: Fit) -> None:
    db.delete(fit)
    db.flush()


def used_image_ids(db: Session, image_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these images already belong to a fit."""
    return set(db.scalars(select(FitImage.image_id).where(FitImage.image_id.in_(image_ids))))


def list_newest(
    db: Session,
    *,
    limit: int,
    cursor: Cursor | None,
    user_id: uuid.UUID | None = None,
    user_ids=None,
    include_user_id: uuid.UUID | None = None,
    viewer_id: uuid.UUID | None = None,
    public_only: bool = False,
) -> list[Fit]:
    """Fits by active users, newest first. Returns up to `limit` rows.

    Enforces Closet Privacy Tiers:
    - Explore feed (public_only=True): public fits only.
    - Other users' profiles: public and close_friends (vault excluded).
    - Own profile: all fits including vault drafts.
    """
    statement = select(Fit).join(Fit.author).where(User.is_active)

    if public_only:
        statement = statement.where(Fit.privacy_tier == "public")
    elif user_id is not None:
        statement = statement.where(Fit.user_id == user_id)
        if viewer_id != user_id:
            statement = statement.where(Fit.privacy_tier != "vault")
    elif user_ids is not None:
        authors = Fit.user_id.in_(user_ids)
        if include_user_id is not None:
            authors = or_(authors, Fit.user_id == include_user_id)
        statement = statement.where(authors)
        # In following feed, exclude vault drafts
        statement = statement.where(Fit.privacy_tier != "vault")

    if cursor is not None:
        statement = statement.where(
            or_(
                Fit.created_at < cursor.created_at,
                and_(Fit.created_at == cursor.created_at, Fit.id < cursor.id),
            )
        )
    statement = statement.order_by(Fit.created_at.desc(), Fit.id.desc()).limit(limit)
    return list(db.scalars(with_details(statement)))
