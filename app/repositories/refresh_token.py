"""Database access for refresh tokens. Queries only: no business rules, and never commits."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.refresh_token import RefreshToken


def get_by_hash(db: Session, token_hash: str) -> RefreshToken | None:
    # populate_existing so revoked_at reflects the database, not a stale copy in the session.
    return db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .execution_options(populate_existing=True)
    )


def add(db: Session, refresh_token: RefreshToken) -> RefreshToken:
    db.add(refresh_token)
    db.flush()
    return refresh_token


def revoke(db: Session, token_id: uuid.UUID, now: datetime) -> bool:
    """Revoke the token if it isn't already. Returns False if it was already revoked.

    A single conditional UPDATE, so two concurrent requests can't both revoke (and rotate)
    the same token.
    """
    result = db.execute(
        update(RefreshToken)
        .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount == 1


def revoke_family(db: Session, family_id: uuid.UUID, now: datetime) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
