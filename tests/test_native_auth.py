"""Native apps (iOS/Android) get the refresh token in the response body instead of a cookie."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import auth as auth_service

from .test_refresh_logout import backdate_revocation

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


def native_login(client: TestClient) -> str:
    """Log in as a native app and return the refresh token from the body."""
    response = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD, "client": "native"})
    assert response.status_code == 200
    return response.json()["refresh_token"]


def native_refresh(client: TestClient, refresh_token: str):
    return client.post(REFRESH_URL, json={"refresh_token": refresh_token})


def web_login(client: TestClient) -> str:
    response = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD})
    return response.cookies["refresh_token"]


# --- login -------------------------------------------------------------------------------


def test_native_login_returns_refresh_token_in_body_and_sets_no_cookie(client: TestClient) -> None:
    response = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD, "client": "native"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "refresh_token", "refresh_expires_in"}
    assert body["refresh_expires_in"] == settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    assert "set-cookie" not in response.headers


def test_web_login_is_unchanged_by_default(client: TestClient) -> None:
    response = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD, "client": "web"})

    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    assert response.headers["set-cookie"].startswith("refresh_token=")


def test_unknown_client_is_rejected(client: TestClient) -> None:
    response = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD, "client": "tv"})

    assert response.status_code == 422


# --- refresh -----------------------------------------------------------------------------


def test_native_refresh_rotates_token_in_body(client: TestClient) -> None:
    old = native_login(client)

    response = native_refresh(client, old)

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    new = response.json()["refresh_token"]
    assert new != old
    access_token = response.json()["access_token"]
    assert client.get(ME_URL, headers={"Authorization": f"Bearer {access_token}"}).status_code == 200
    # Rotated: the new token works.
    assert native_refresh(client, new).status_code == 200


def test_native_refresh_ignores_cookie(client: TestClient) -> None:
    web_login(client)  # the client's cookie jar now holds a valid web refresh token

    response = native_refresh(client, "not-a-real-token")

    assert response.status_code == 401


def test_cookie_refresh_never_returns_token_in_body(client: TestClient) -> None:
    # A script injected into the website can send the cookie, but must not be able to read it.
    web_login(client)

    response = client.post(REFRESH_URL)

    assert response.status_code == 200
    assert "refresh_token" not in response.json()
    assert response.headers["set-cookie"].startswith("refresh_token=")


def test_native_refresh_rejects_empty_token(client: TestClient) -> None:
    assert native_refresh(client, "").status_code == 422


def test_native_token_reuse_revokes_that_session(client: TestClient, db: Session) -> None:
    old = native_login(client)
    rotated = native_refresh(client, old).json()["refresh_token"]
    backdate_revocation(db, old, seconds=int(auth_service.REUSE_GRACE_PERIOD.total_seconds()) + 1)

    assert native_refresh(client, old).status_code == 401
    assert native_refresh(client, rotated).status_code == 401


# --- logout ------------------------------------------------------------------------------


def test_native_logout_revokes_token(client: TestClient) -> None:
    refresh_token = native_login(client)

    response = client.post(LOGOUT_URL, json={"refresh_token": refresh_token})

    assert response.status_code == 204
    assert "set-cookie" not in response.headers
    assert native_refresh(client, refresh_token).status_code == 401


def test_native_logout_leaves_web_session_alone(client: TestClient) -> None:
    web_login(client)
    refresh_token = native_login(client)

    client.post(LOGOUT_URL, json={"refresh_token": refresh_token})

    assert client.post(REFRESH_URL).status_code == 200
