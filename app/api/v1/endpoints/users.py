from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, PageCursor, PageLimit, SessionDep
from app.core.pagination import InvalidCursorError
from app.schemas.error import ErrorResponse
from app.schemas.fit import FitRead
from app.schemas.pagination import Page
from app.schemas.user import ProfileRead, UserPrivacySettingsRead, UserPrivacySettingsUpdate, UserRead, UserSearchResult, UserSummary, UserUpdate
from app.services.engagement import list_saved_fits
from app.services import follow as follow_service
from app.services.fit import list_fits
from app.services.image import ImageNotFoundError
from app.services.user import UsernameTakenError, get_user_by_username, search_users as search_users_service, update_privacy_settings, update_profile

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


@router.get(
    "/me/privacy",
    response_model=UserPrivacySettingsRead,
    summary="Get your closet privacy settings",
    responses=UNAUTHORIZED_RESPONSE,
)
def read_privacy_settings(current_user: CurrentUser) -> UserPrivacySettingsRead:
    """Return the user's default closet privacy."""
    return UserPrivacySettingsRead.model_validate(current_user)


@router.patch(
    "/me/privacy",
    response_model=UserPrivacySettingsRead,
    summary="Update your closet privacy settings",
    responses=UNAUTHORIZED_RESPONSE,
)
def update_privacy(
    changes: UserPrivacySettingsUpdate, current_user: CurrentUser, db: SessionDep
) -> UserPrivacySettingsRead:
    """Update the user's default closet privacy."""
    updated = update_privacy_settings(db, current_user, changes)
    return UserPrivacySettingsRead.model_validate(updated)


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
    "/search",
    response_model=list[UserSearchResult],
    summary="Search users",
    responses=UNAUTHORIZED_RESPONSE,
)
def search_users(
    current_user: CurrentUser,
    db: SessionDep,
    q: str = "",
    limit: PageLimit = 20,
) -> list[UserSearchResult]:
    """Search users by username or full name."""
    return search_users_service(db, current_user, query=q, limit=limit)


@router.get(
    "/{username}",
    response_model=ProfileRead,
    summary="Get a user's profile",
    responses={**UNAUTHORIZED_RESPONSE, **USER_NOT_FOUND_RESPONSE},
)
def read_profile(username: str, current_user: CurrentUser, db: SessionDep) -> ProfileRead:
    """Return someone's public profile with counts. Doesn't include their email."""
    try:
        return ProfileRead.from_view(follow_service.get_profile(db, current_user, username))
    except follow_service.UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from None


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


def _user_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.put(
    "/{username}/follow",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Follow a user",
    responses={
        **UNAUTHORIZED_RESPONSE,
        **USER_NOT_FOUND_RESPONSE,
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "content": {"application/json": {"example": {"detail": "You can't follow yourself"}}},
        },
    },
)
def follow_user(username: str, current_user: CurrentUser, db: SessionDep) -> None:
    """Idempotent: following someone you already follow does nothing."""
    try:
        follow_service.follow(db, current_user, username)
    except follow_service.UserNotFoundError:
        raise _user_not_found() from None
    except follow_service.CannotFollowSelfError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You can't follow yourself"
        ) from None


@router.delete(
    "/{username}/follow",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unfollow a user",
    responses={**UNAUTHORIZED_RESPONSE, **USER_NOT_FOUND_RESPONSE},
)
def unfollow_user(username: str, current_user: CurrentUser, db: SessionDep) -> None:
    """Idempotent."""
    try:
        follow_service.unfollow(db, current_user, username)
    except follow_service.UserNotFoundError:
        raise _user_not_found() from None


def _user_list(list_users, username: str, db, limit: int, cursor: str | None) -> Page[UserSummary]:
    try:
        page = list_users(db, username, limit=limit, cursor=cursor)
    except follow_service.UserNotFoundError:
        raise _user_not_found() from None
    except InvalidCursorError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor") from None
    return Page(
        items=[UserSummary.model_validate(user) for user in page.users], next_cursor=page.next_cursor
    )


@router.get(
    "/{username}/followers",
    response_model=Page[UserSummary],
    summary="List a user's followers",
    responses={**UNAUTHORIZED_RESPONSE, **USER_NOT_FOUND_RESPONSE, **INVALID_CURSOR_RESPONSE},
)
def read_followers(
    username: str,
    current_user: CurrentUser,
    db: SessionDep,
    limit: PageLimit = 20,
    cursor: PageCursor = None,
) -> Page[UserSummary]:
    """Most recent followers first."""
    return _user_list(follow_service.list_followers, username, db, limit, cursor)


@router.get(
    "/{username}/following",
    response_model=Page[UserSummary],
    summary="List who a user follows",
    responses={**UNAUTHORIZED_RESPONSE, **USER_NOT_FOUND_RESPONSE, **INVALID_CURSOR_RESPONSE},
)
def read_following(
    username: str,
    current_user: CurrentUser,
    db: SessionDep,
    limit: PageLimit = 20,
    cursor: PageCursor = None,
) -> Page[UserSummary]:
    """Most recently followed first."""
    return _user_list(follow_service.list_following, username, db, limit, cursor)
