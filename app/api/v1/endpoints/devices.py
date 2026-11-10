from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.device import DeviceRead, DeviceRegister
from app.services import device as service

router = APIRouter()


@router.post("", response_model=DeviceRead, summary="Register or refresh a push token")
def register_device(data: DeviceRegister, current_user: CurrentUser, db: SessionDep) -> DeviceRead:
    """Call after login and on every app start; it's an upsert keyed by `token`."""
    return service.register(db, current_user, data)


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a push token")
def unregister_device(token: str, current_user: CurrentUser, db: SessionDep) -> None:
    """Call on logout. Idempotent."""
    service.unregister(db, current_user, token)
