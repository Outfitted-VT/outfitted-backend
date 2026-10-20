from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response, status

from app.api.deps import SessionDep
from app.core.config import settings
from app.schemas.auth import LoginRequest, RefreshRequest, Token
from app.schemas.error import ErrorResponse
from app.schemas.user import UserCreate, UserRead
from app.services import auth as auth_service
from app.services.user import EmailAlreadyRegisteredError, UsernameTakenError, create_user

router = APIRouter()


@router.post(
    "/signup",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The email or username is already in use.",
            "content": {
                "application/json": {
                    "examples": {
                        "email": {"value": {"detail": "Email is already registered"}},
                        "username": {"value": {"detail": "Username is already taken"}},
                    }
                }
            },
        },
    },
)
def signup(user_in: UserCreate, db: SessionDep) -> UserRead:
    """
    Register a new user with an email and password. Does not log the user in;
    call `POST /auth/login` afterwards to get a token.

    - **email**: must be a valid email; stored lowercase, so sign-up is case-insensitive.
    - **username**: 3-30 characters of lowercase letters, numbers, `_` and `.`;
      stored lowercase. Shown publicly on the profile and fits.
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
    except UsernameTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username is already taken"
        ) from None
    return UserRead.model_validate(user)


REFRESH_COOKIE_NAME = "refresh_token"

RefreshCookie = Annotated[
    str | None,
    Cookie(
        alias=REFRESH_COOKIE_NAME,
        description="Set by `/auth/login` and `/auth/refresh`; the browser sends it automatically.",
    ),
]

INVALID_REFRESH_TOKEN_RESPONSE = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Refresh token missing, invalid, expired, already used, or logged out.",
        "content": {"application/json": {"example": {"detail": "Invalid or expired refresh token"}}},
    },
}


def _set_refresh_cookie(response: Response, tokens: auth_service.IssuedTokens) -> None:
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        tokens.refresh_token,
        max_age=tokens.refresh_token_max_age,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def _clear_refresh_cookie(response: Response) -> None:
    # Attributes must match the ones used to set it, or the browser keeps the cookie.
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def _token_response(
    response: Response, tokens: auth_service.IssuedTokens, *, native: bool
) -> Token:
    # Exactly one of the two: native clients get the refresh token in the body, browsers get
    # it as a cookie. A cookie request must never get it in the body, or a script injected
    # into the website could turn the HttpOnly cookie into a token it can read.
    if native:
        return Token(
            access_token=tokens.access_token,
            expires_in=tokens.expires_in,
            refresh_token=tokens.refresh_token,
            refresh_expires_in=tokens.refresh_token_max_age,
        )
    _set_refresh_cookie(response, tokens)
    return Token(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post(
    "/login",
    response_model=Token,
    response_model_exclude_none=True,
    summary="Log in",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Wrong email or password, or the account is deactivated.",
            "content": {
                "application/json": {"example": {"detail": "Incorrect email or password"}}
            },
        },
    },
)
def login(credentials: LoginRequest, response: Response, db: SessionDep) -> Token:
    """
    Exchange an email and password for tokens.

    - **Access token** (response body): send it on protected requests as
      `Authorization: Bearer <access_token>`. Expires after `expires_in` seconds.
    - **Refresh token** (`refresh_token` HttpOnly cookie): JavaScript can't read it; the
      browser sends it to `/auth/refresh` and `/auth/logout` automatically.
      Call this endpoint with `credentials: "include"` so the browser stores the cookie.

    **Native apps** send `"client": "native"`: the refresh token comes back in the body as
    `refresh_token` (lifetime in seconds: `refresh_expires_in`) and no cookie is set. Keep it
    in the device's secure storage (Keychain / Keystore).
    """
    try:
        tokens = auth_service.login(db, credentials.email, credentials.password)
    except auth_service.InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    return _token_response(response, tokens, native=credentials.client == "native")


@router.post(
    "/refresh",
    response_model=Token,
    response_model_exclude_none=True,
    summary="Get a new access token",
    responses=INVALID_REFRESH_TOKEN_RESPONSE,
)
def refresh(
    response: Response,
    db: SessionDep,
    body: RefreshRequest | None = None,
    refresh_token: RefreshCookie = None,
) -> Token:
    """
    Use the refresh token to get a new access token.

    - **Browsers**: send no body; call with `credentials: "include"` so the cookie is sent.
    - **Native apps**: send `{"refresh_token": "..."}`. Any cookie is ignored, and the new
      refresh token comes back in the body.

    The refresh token is rotated: the old one stops working and a new one is issued.
    Also call this on app start to restore a session when there's no access token.
    """
    native = body is not None
    raw_token = body.refresh_token if native else refresh_token
    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
        )
    try:
        tokens = auth_service.refresh(db, raw_token)
    except auth_service.InvalidRefreshTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
        ) from None
    return _token_response(response, tokens, native=native)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out",
)
def logout(
    response: Response,
    db: SessionDep,
    body: RefreshRequest | None = None,
    refresh_token: RefreshCookie = None,
) -> None:
    """
    Revoke the refresh token. Browsers: send no body, call with `credentials: "include"`, and
    the cookie is cleared. Native apps: send `{"refresh_token": "..."}`.

    Always returns **204**. The access token keeps working until it expires
    (at most `expires_in` seconds), so delete it on the client too.
    """
    if body is not None:
        auth_service.logout(db, body.refresh_token)
        return
    if refresh_token is not None:
        auth_service.logout(db, refresh_token)
    _clear_refresh_cookie(response)
