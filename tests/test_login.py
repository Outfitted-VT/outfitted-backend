import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.security import create_access_token
from app.repositories import user as user_repository

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/users/me"

EMAIL = "jane@example.com"
PASSWORD = "s3cure-passw0rd"


@pytest.fixture
def registered_user(client: TestClient) -> dict:
    response = client.post(SIGNUP_URL, json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post(LOGIN_URL, json={"email": email, "password": password})


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_returns_token(client: TestClient, registered_user: dict) -> None:
    response = login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert body["access_token"]


def test_login_email_is_case_insensitive(client: TestClient, registered_user: dict) -> None:
    assert login(client, email="JANE@Example.com").status_code == 200


@pytest.mark.parametrize(
    ("email", "password"),
    [(EMAIL, "wrong-password"), ("nobody@example.com", PASSWORD)],
    ids=["wrong-password", "unknown-email"],
)
def test_login_rejects_bad_credentials(
    client: TestClient, registered_user: dict, email: str, password: str
) -> None:
    response = login(client, email=email, password=password)

    # Same response either way, so attackers can't tell which emails are registered.
    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}


def test_login_rejects_inactive_user(client: TestClient, db: Session, registered_user: dict) -> None:
    user = user_repository.get_by_email(db, EMAIL)
    user.is_active = False
    db.commit()

    assert login(client).status_code == 401


def test_me_returns_current_user(client: TestClient, registered_user: dict) -> None:
    token = login(client).json()["access_token"]

    response = client.get(ME_URL, headers=auth_header(token))

    assert response.status_code == 200
    assert response.json() == registered_user


def test_me_requires_token(client: TestClient) -> None:
    response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_me_rejects_garbage_token(client: TestClient) -> None:
    assert client.get(ME_URL, headers=auth_header("not-a-jwt")).status_code == 401


def test_me_rejects_expired_token(client: TestClient, registered_user: dict) -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    token = jwt.encode(
        {"sub": registered_user["id"], "iat": past, "exp": past + timedelta(hours=1)},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    assert client.get(ME_URL, headers=auth_header(token)).status_code == 401


def test_me_rejects_token_signed_with_other_key(client: TestClient, registered_user: dict) -> None:
    token = jwt.encode(
        {"sub": registered_user["id"], "exp": datetime.now(UTC) + timedelta(hours=1)},
        "some-other-secret-key-that-is-long-enough",
        algorithm="HS256",
    )

    assert client.get(ME_URL, headers=auth_header(token)).status_code == 401


def test_me_rejects_token_for_deleted_user(client: TestClient) -> None:
    token = create_access_token(uuid.uuid4())

    assert client.get(ME_URL, headers=auth_header(token)).status_code == 401


def test_me_rejects_inactive_user(client: TestClient, db: Session, registered_user: dict) -> None:
    token = login(client).json()["access_token"]
    user = user_repository.get_by_email(db, EMAIL)
    user.is_active = False
    db.commit()

    assert client.get(ME_URL, headers=auth_header(token)).status_code == 401


def test_secret_key_required_outside_development() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENVIRONMENT="production")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENVIRONMENT="production", SECRET_KEY="too-short")

    Settings(_env_file=None, ENVIRONMENT="production", SECRET_KEY="x" * 32)
