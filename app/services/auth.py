"""Login sessions: issuing, rotating, and revoking tokens."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, generate_refresh_token, hash_refresh_token
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories import refresh_token as refresh_token_repository
from app.repositories import user as user_repository
from app.services.user import authenticate

# A refresh token reused within this window after being rotated is treated as a race
# (e.g. two browser tabs refreshing at once with the same cookie), not as theft.
REUSE_GRACE_PERIOD = timedelta(seconds=10)


class InvalidCredentialsError(Exception):
    pass


class InvalidRefreshTokenError(Exception):
    pass


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_token_max_age: int


def _as_utc(value: datetime) -> datetime:
    # SQLite drops timezone info; timestamps are always stored in UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _issue_tokens(db: Session, user: User, family_id: uuid.UUID) -> IssuedTokens:
    raw_refresh_token = generate_refresh_token()
    refresh_token_lifetime = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_token_repository.add(
        db,
        RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=datetime.now(UTC) + refresh_token_lifetime,
        ),
    )
    db.commit()
    return IssuedTokens(
        access_token=create_access_token(user.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=raw_refresh_token,
        refresh_token_max_age=int(refresh_token_lifetime.total_seconds()),
    )


def login(db: Session, email: str, password: str) -> IssuedTokens:
    user = authenticate(db, email, password)
    if user is None or not user.is_active:
        raise InvalidCredentialsError
    return _issue_tokens(db, user, family_id=uuid.uuid4())


def refresh(db: Session, raw_refresh_token: str) -> IssuedTokens:
    """Exchange a refresh token for new tokens. The old refresh token stops working."""
    now = datetime.now(UTC)
    stored = refresh_token_repository.get_by_hash(db, hash_refresh_token(raw_refresh_token))
    if stored is None or _as_utc(stored.expires_at) <= now:
        raise InvalidRefreshTokenError

    if not refresh_token_repository.revoke(db, stored.id, now):
        revoked_recently = (
            stored.revoked_at is not None
            and now - _as_utc(stored.revoked_at) <= REUSE_GRACE_PERIOD
        )
        if not revoked_recently:
            # Reused long after rotation or logout: someone else likely has a copy. We can't
            # tell which copy is legitimate, so end this login session everywhere.
            refresh_token_repository.revoke_family(db, stored.family_id, now)
            db.commit()
        raise InvalidRefreshTokenError

    user = user_repository.get(db, stored.user_id)
    if user is None or not user.is_active:
        db.commit()
        raise InvalidRefreshTokenError

    # Commits the revocation of the old token together with the new one.
    return _issue_tokens(db, user, family_id=stored.family_id)


def logout(db: Session, raw_refresh_token: str) -> None:
    """Revoke the refresh token. Unknown or already-revoked tokens are ignored."""
    stored = refresh_token_repository.get_by_hash(db, hash_refresh_token(raw_refresh_token))
    if stored is not None:
        refresh_token_repository.revoke(db, stored.id, datetime.now(UTC))
        db.commit()
