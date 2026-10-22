from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.garments import GarmentDetector, get_garment_detector
from app.services.user import get_user
from app.storage import Storage, get_storage
from app.tryon import TryOnGenerator, get_tryon_generator

SessionDep = Annotated[Session, Depends(get_db)]
StorageDep = Annotated[Storage, Depends(get_storage)]
TryOnGeneratorDep = Annotated[TryOnGenerator, Depends(get_tryon_generator)]
GarmentDetectorDep = Annotated[GarmentDetector, Depends(get_garment_detector)]

# auto_error=False so a missing header returns our 401 instead of FastAPI's default 403.
bearer_scheme = HTTPBearer(auto_error=False, description="Access token from `POST /auth/login`")


def get_current_user(
    db: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise unauthorized

    user = get_user(db, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

PageLimit = Annotated[int, Query(ge=1, le=50, description="Items per page.")]
PageCursor = Annotated[str | None, Query(description="`next_cursor` from the previous page.")]
