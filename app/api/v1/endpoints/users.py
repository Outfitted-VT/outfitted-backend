from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, PageCursor, PageLimit, SessionDep
from app.core.pagination import InvalidCursorError
from app.schemas.error import ErrorResponse
from app.schemas.fit import FitRead
from app.schemas.pagination import Page
from app.schemas.user import ProfileRead, UserRead, UserUpdate
from app.services.engagement import list_saved_fits
from app.services.fit import list_fits
from app.services.image import ImageNotFoundError
from app.services.user import UsernameTakenError, get_user_by_username, update_profile

router = APIRouter()

UNAUTHORIZED_RESPONSE = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Missing, invalid, or expired access token.",
        "content": {"application/json": {"example": {"detail": "Not authenticated"}}},
    },
}

USER_NOT_FOUND_RESPONSE = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "content": {"application/json": {"example": {"detail": "User not found"}}},
    },
}


@router.get(
    "/me", response_model=UserRead, summary="Get your account", responses=UNAUTHORIZED_RESPONSE
)
def read_current_user(current_user: CurrentUser) -> UserRead:
    """Return the logged-in user, including private fields like email."""
    return UserRead.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Update your profile",
    responses={
        **UNAUTHORIZED_RESPONSE,
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "`avatar_image_id` doesn't exist or wasn't uploaded by you.",
            "content": {"application/json": {"example": {"detail": "Image not found"}}},
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The username is already taken.",
            "content": {"application/json": {"example": {"detail": "Username is already taken"}}},
        },
    },
)
def update_current_user(
    changes: UserUpdate, current_user: CurrentUser, db: SessionDep
) -> UserRead:
    """
    Change only the fields you send. Omitted fields stay the same; send `null` to clear
    `full_name`, `bio`, or `avatar_image_id`.

    To set an avatar, upload it with `POST /images` and send its `id` as `avatar_image_id`.
    """
    try:
        user = update_profile(db, current_user, changes)
    except UsernameTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username is already taken"
        ) from None
    except ImageNotFoundError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image not found") from None
    return UserRead.model_validate(user)


INVALID_CURSOR_RESPONSE = {
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponse,
        "content": {"application/json": {"example": {"detail": "Invalid cursor"}}},
    },
}


@router.get(
    "/me/saved",
    response_model=Page[FitRead],
    summary="List your saved fits",
    responses={**UNAUTHORIZED_RESPONSE, **INVALID_CURSOR_RESPONSE},
)
def read_saved_fits(
    current_user: CurrentUser, db: SessionDep, limit: PageLimit = 20, cursor: PageCursor = None
) -> Page[FitRead]:
    """Fits you saved, most recently saved first. Only you can see your saves."""
    try:
        page = list_saved_fits(db, current_user, limit=limit, cursor=cursor)
    except InvalidCursorError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor") from None
    return Page(items=[FitRead.from_view(view) for view in page.views], next_cursor=page.next_cursor)


@router.get(
    "/{username}",
    response_model=ProfileRead,
    summary="Get a user's profile",
    responses={**UNAUTHORIZED_RESPONSE, **USER_NOT_FOUND_RESPONSE},
)
def read_profile(username: str, current_user: CurrentUser, db: SessionDep) -> ProfileRead:
    """Return someone's public profile. Doesn't include their email."""
    user = get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return ProfileRead.model_validate(user)


@router.get(
    "/{username}/fits",
    response_model=Page[FitRead],
    summary="List a user's fits",
    responses={**UNAUTHORIZED_RESPONSE, **USER_NOT_FOUND_RESPONSE, **INVALID_CURSOR_RESPONSE},
)
def read_user_fits(
    username: str,
    current_user: CurrentUser,
    db: SessionDep,
    limit: PageLimit = 20,
    cursor: PageCursor = None,
) -> Page[FitRead]:
    """The user's fits, newest first."""
    user = get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        page = list_fits(db, current_user, limit=limit, cursor=cursor, author=user)
    except InvalidCursorError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor") from None
    return Page(items=[FitRead.from_view(view) for view in page.views], next_cursor=page.next_cursor)
