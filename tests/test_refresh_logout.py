from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.security import hash_refresh_token
from app.models.refresh_token import RefreshToken
from app.repositories import refresh_token as refresh_token_repository
from app.repositories import user as user_repository
from app.services import auth as auth_service

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/users/me"

EMAIL = "jane@example.com"
PASSWORD = "s3cure-passw0rd"


@pytest.fixture(autouse=True)
def registered_user(client: TestClient) -> None:
    client.post(SIGNUP_URL, json={"email": EMAIL, "username": "jane", "password": PASSWORD})


def login(client: TestClient) -> str:
    """Log in and return the refresh token the server set as a cookie."""
    response = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    return response.cookies["refresh_token"]


def refresh_with(client: TestClient, refresh_token: str):
    """Send a specific refresh token, bypassing the client's cookie jar."""
    return client.post(REFRESH_URL, headers={"Cookie": f"refresh_token={refresh_token}"})


def backdate_revocation(db: Session, refresh_token: str, seconds: int) -> None:
    stored = refresh_token_repository.get_by_hash(db, hash_refresh_token(refresh_token))
    stored.revoked_at = datetime.now(UTC) - timedelta(seconds=seconds)
    db.commit()


# --- login -------------------------------------------------------------------------------


def test_login_sets_refresh_cookie_not_in_body(client: TestClient) -> None:
    response = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD})

    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("refresh_token=")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert f"Path={settings.refresh_cookie_path}" in cookie
    assert f"Max-Age={settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60}" in cookie


def test_only_the_hash_is_stored(client: TestClient, db: Session) -> None:
    refresh_token = login(client)
    stored = db.scalar(select(RefreshToken))

    assert stored.token_hash == hash_refresh_token(refresh_token)
    assert stored.token_hash != refresh_token


# --- refresh -----------------------------------------------------------------------------


def test_refresh_uses_cookie_and_returns_working_access_token(client: TestClient) -> None:
    old_refresh_token = login(client)

    response = client.post(REFRESH_URL)  # cookie sent automatically from the jar

    assert response.status_code == 200
    assert response.cookies["refresh_token"] != old_refresh_token
    access_token = response.json()["access_token"]
    me = client.get(ME_URL, headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200


def test_refresh_cookie_not_sent_outside_auth_path(client: TestClient) -> None:
    login(client)

    request = client.build_request("GET", ME_URL)

    assert "refresh_token" not in request.headers.get("cookie", "")


def test_refresh_without_cookie(client: TestClient) -> None:
    response = client.post(REFRESH_URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired refresh token"}


def test_refresh_rejects_unknown_token(client: TestClient) -> None:
    assert refresh_with(client, "not-a-real-token").status_code == 401


def test_refresh_rejects_expired_token(client: TestClient, db: Session) -> None:
    refresh_token = login(client)
    stored = refresh_token_repository.get_by_hash(db, hash_refresh_token(refresh_token))
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    assert refresh_with(client, refresh_token).status_code == 401


def test_refresh_rejects_inactive_user(client: TestClient, db: Session) -> None:
    refresh_token = login(client)
    user = user_repository.get_by_email(db, EMAIL)
    user.is_active = False
    db.commit()

    assert refresh_with(client, refresh_token).status_code == 401


# --- rotation and reuse --------------------------------------------------------------------


def test_reuse_within_grace_period_does_not_revoke_session(client: TestClient) -> None:
    old = login(client)
    rotated = refresh_with(client, old).cookies["refresh_token"]

    # A second tab sent the same cookie at the same moment.
    assert refresh_with(client, old).status_code == 401

    # Not treated as theft: the rotated token still works.
    assert refresh_with(client, rotated).status_code == 200


def test_reuse_after_grace_period_revokes_that_session(client: TestClient, db: Session) -> None:
    old = login(client)
    rotated = refresh_with(client, old).cookies["refresh_token"]
    backdate_revocation(db, old, seconds=int(auth_service.REUSE_GRACE_PERIOD.total_seconds()) + 1)

    # Someone replays the old token well after it was rotated.
    assert refresh_with(client, old).status_code == 401

    # The whole session chain is revoked, including the legitimately rotated token.
    assert refresh_with(client, rotated).status_code == 401


def test_reuse_only_revokes_that_session_not_other_devices(
    client: TestClient, db: Session
) -> None:
    old = login(client)
    other_device = login(client)
    refresh_with(client, old)
    backdate_revocation(db, old, seconds=60)

    refresh_with(client, old)

    assert refresh_with(client, other_device).status_code == 200


def test_revoke_is_one_shot(client: TestClient, db: Session) -> None:
    refresh_token = login(client)
    stored = refresh_token_repository.get_by_hash(db, hash_refresh_token(refresh_token))
    now = datetime.now(UTC)

    # Two concurrent refreshes race to revoke the same token: only one may win.
    assert refresh_token_repository.revoke(db, stored.id, now) is True
    assert refresh_token_repository.revoke(db, stored.id, now) is False


# --- logout ------------------------------------------------------------------------------


def test_logout_revokes_token_and_clears_cookie(client: TestClient) -> None:
    refresh_token = login(client)

    response = client.post(LOGOUT_URL)

    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith('refresh_token="";') or cookie.startswith("refresh_token=;")
    assert "Max-Age=0" in cookie
    assert f"Path={settings.refresh_cookie_path}" in cookie
    assert refresh_with(client, refresh_token).status_code == 401


def test_logout_only_ends_that_session(client: TestClient) -> None:
    this_device = login(client)
    other_device = login(client)

    client.post(LOGOUT_URL, headers={"Cookie": f"refresh_token={this_device}"})

    assert refresh_with(client, other_device).status_code == 200


def test_logout_without_cookie_still_succeeds(client: TestClient) -> None:
    assert client.post(LOGOUT_URL).status_code == 204


# --- settings ----------------------------------------------------------------------------


def test_samesite_none_requires_secure() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, REFRESH_COOKIE_SAMESITE="none", REFRESH_COOKIE_SECURE=False)
