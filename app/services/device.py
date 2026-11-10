"""Push device tokens: registered on login and app start, removed on logout or when a provider rejects them."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.mixins import utcnow
from app.models.device import DeviceToken
from app.models.user import User
from app.repositories import device as repo
from app.schemas.device import DeviceRegister


def register(db: Session, user: User, data: DeviceRegister) -> DeviceToken:
    """Add the token, or refresh it. A token registered by someone else moves to this user (a shared phone)."""
    now = utcnow()
    device = repo.get_by_token(db, data.token)
    if device is None:
        device = DeviceToken(user_id=user.id, platform=data.platform, token=data.token, created_at=now)
        try:
            repo.add(db, device)
        except IntegrityError:
            db.rollback()
            device = repo.get_by_token(db, data.token)
    device.user_id = user.id
    device.platform = data.platform
    device.app_version = data.app_version
    device.last_seen_at = now
    db.commit()
    return device


def unregister(db: Session, user: User, token: str) -> None:
    """Idempotent. Only removes the token if it's yours."""
    repo.remove(db, token, user.id)
    db.commit()
