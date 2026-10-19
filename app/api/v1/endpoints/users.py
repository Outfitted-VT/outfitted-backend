from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.schemas.error import ErrorResponse
from app.schemas.user import UserRead

router = APIRouter()


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get the logged-in user",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Missing, invalid, or expired token.",
            "content": {"application/json": {"example": {"detail": "Not authenticated"}}},
        },
    },
)
def read_current_user(current_user: CurrentUser) -> UserRead:
    """Return the user the access token belongs to."""
    return UserRead.model_validate(current_user)
