from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.services.user import get_user_by_email

SIGNUP_URL = "/api/v1/auth/signup"


def test_signup_creates_user(client: TestClient, db: Session) -> None:
    response = client.post(
        SIGNUP_URL,
        json={"email": "Jane@Example.com", "password": "s3cure-passw0rd", "full_name": "Jane Doe"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "jane@example.com"
    assert body["full_name"] == "Jane Doe"
    assert body["is_active"] is True
    assert {"id", "created_at"} <= body.keys()
    assert "password" not in body
    assert "hashed_password" not in body

    user = get_user_by_email(db, "jane@example.com")
    assert user is not None
    assert user.hashed_password != "s3cure-passw0rd"
    assert verify_password("s3cure-passw0rd", user.hashed_password)


def test_signup_full_name_is_optional(client: TestClient) -> None:
    response = client.post(SIGNUP_URL, json={"email": "a@example.com", "password": "s3cure-passw0rd"})

    assert response.status_code == 201
    assert response.json()["full_name"] is None


def test_signup_duplicate_email_is_case_insensitive(client: TestClient) -> None:
    client.post(SIGNUP_URL, json={"email": "jane@example.com", "password": "s3cure-passw0rd"})
    response = client.post(SIGNUP_URL, json={"email": "JANE@example.com", "password": "another-pass1"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Email is already registered"}


def test_signup_rejects_invalid_email(client: TestClient) -> None:
    response = client.post(SIGNUP_URL, json={"email": "not-an-email", "password": "s3cure-passw0rd"})

    assert response.status_code == 422


def test_signup_rejects_short_password(client: TestClient) -> None:
    response = client.post(SIGNUP_URL, json={"email": "a@example.com", "password": "short"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "password"]


def test_validation_errors_do_not_echo_input(client: TestClient) -> None:
    response = client.post(SIGNUP_URL, json={"email": "a@example.com", "password": "secret1"})

    assert response.status_code == 422
    assert "secret1" not in response.text


def test_signup_created_at_is_utc(client: TestClient) -> None:
    response = client.post(SIGNUP_URL, json={"email": "a@example.com", "password": "s3cure-passw0rd"})

    assert response.json()["created_at"].endswith(("Z", "+00:00"))
