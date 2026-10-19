from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep
from app.schemas.error import ErrorResponse
from app.schemas.user import UserCreate, UserRead
from app.services.user import EmailAlreadyRegisteredError, create_user

router = APIRouter()


@router.post(
    "/signup",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "An account with this email already exists.",
            "content": {
                "application/json": {"example": {"detail": "Email is already registered"}}
            },
        },
    },
)
def signup(user_in: UserCreate, db: SessionDep) -> UserRead:
    """
    Register a new user with an email and password.

    - **email**: must be a valid email; stored lowercase, so sign-up is case-insensitive.
    - **password**: 8–128 characters. Never returned by the API.
    - **full_name**: optional, up to 100 characters.

    Returns the created user. Validation failures return **422** with a `detail` list
    describing each invalid field.
    """
    try:
        user = create_user(db, user_in)
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email is already registered"
        ) from None
    return UserRead.model_validate(user)
