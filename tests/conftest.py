import io
import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import app
from app.models import Base
from app.storage import LocalStorage, get_storage

# In-memory SQLite shared across connections, so tests never touch the real database.
engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

PASSWORD = "s3cure-passw0rd"


@pytest.fixture
def db() -> Generator[Session, None, None]:
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    """Uploads go to a temporary directory instead of media/."""
    return LocalStorage(tmp_path)


@pytest.fixture
def client(db: Session, storage: LocalStorage) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_storage] = lambda: storage
    # HTTPS so the client sends the Secure refresh cookie, like a browser would.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@dataclass(frozen=True)
class AuthedUser:
    id: uuid.UUID
    username: str
    headers: dict[str, str]


@pytest.fixture
def create_user(client: TestClient) -> Callable[..., AuthedUser]:
    """Sign up and log in a user; returns their id, username, and auth headers."""

    def _create_user(username: str = "jane", full_name: str | None = None) -> AuthedUser:
        email = f"{username}@example.com"
        response = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "username": username, "password": PASSWORD, "full_name": full_name},
        )
        assert response.status_code == 201, response.text
        token = client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        ).json()["access_token"]
        return AuthedUser(
            id=uuid.UUID(response.json()["id"]),
            username=username,
            headers={"Authorization": f"Bearer {token}"},
        )

    return _create_user


def make_image_bytes(
    image_format: str = "JPEG", size: tuple[int, int] = (64, 48), mode: str = "RGB"
) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, color="red").save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.fixture
def upload_image(client: TestClient) -> Callable[[AuthedUser], str]:
    """Upload a small JPEG as the given user and return its image id."""

    def _upload_image(user: AuthedUser) -> str:
        response = client.post(
            "/api/v1/images",
            headers=user.headers,
            files={"file": ("photo.jpg", make_image_bytes(), "image/jpeg")},
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    return _upload_image
