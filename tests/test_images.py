import io
from collections.abc import Callable

from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.storage import LocalStorage
from tests.conftest import AuthedUser, make_image_bytes

IMAGES_URL = "/api/v1/images"


def upload(client: TestClient, user: AuthedUser, data: bytes, filename: str = "photo.jpg"):
    return client.post(IMAGES_URL, headers=user.headers, files={"file": (filename, data, "image/jpeg")})


def stored_image(storage: LocalStorage, url: str) -> Image.Image:
    key = url.removeprefix(settings.MEDIA_BASE_URL.rstrip("/") + "/")
    return Image.open(storage.root / key)


def test_upload_returns_id_url_and_size(
    client: TestClient, create_user: Callable[..., AuthedUser], storage: LocalStorage
) -> None:
    user = create_user()

    response = upload(client, user, make_image_bytes(size=(64, 48)))

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "url", "width", "height", "generated"}
    assert body["generated"] is False
    assert (body["width"], body["height"]) == (64, 48)
    assert body["url"].startswith(settings.MEDIA_BASE_URL)
    assert body["url"].endswith(".webp")
    assert stored_image(storage, body["url"]).format == "WEBP"


def test_upload_accepts_png_and_webp(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    user = create_user()

    assert upload(client, user, make_image_bytes("PNG", mode="RGBA")).status_code == 201
    assert upload(client, user, make_image_bytes("WEBP")).status_code == 201


def test_upload_strips_exif_location(
    client: TestClient, create_user: Callable[..., AuthedUser], storage: LocalStorage
) -> None:
    user = create_user()
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (40.0, 26.0, 46.0)}  # GPS info
    exif[0x010F] = "PhoneMaker"  # camera make
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buffer, format="JPEG", exif=exif)

    url = upload(client, user, buffer.getvalue()).json()["url"]

    assert not stored_image(storage, url).getexif()


def test_upload_applies_exif_orientation(
    client: TestClient, create_user: Callable[..., AuthedUser]
) -> None:
    user = create_user()
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 degrees": a portrait phone photo stored sideways
    buffer = io.BytesIO()
    Image.new("RGB", (80, 40)).save(buffer, format="JPEG", exif=exif)

    body = upload(client, user, buffer.getvalue()).json()

    assert (body["width"], body["height"]) == (40, 80)


def test_upload_scales_down_large_images(
    client: TestClient, create_user: Callable[..., AuthedUser]
) -> None:
    user = create_user()

    body = upload(client, user, make_image_bytes(size=(4096, 1024))).json()

    assert (body["width"], body["height"]) == (2048, 512)


def test_upload_rejects_non_images(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    user = create_user()

    response = upload(client, user, b"definitely not an image", filename="photo.jpg")

    assert response.status_code == 400
    assert response.json() == {"detail": "File is not a supported image"}


def test_upload_rejects_unsupported_format(
    client: TestClient, create_user: Callable[..., AuthedUser]
) -> None:
    user = create_user()

    response = upload(client, user, make_image_bytes("GIF", mode="P"))

    assert response.status_code == 400
    assert response.json() == {"detail": "Image must be JPEG, PNG, or WebP"}


def test_upload_rejects_too_large_file(
    client: TestClient, create_user: Callable[..., AuthedUser], monkeypatch
) -> None:
    user = create_user()
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 100)

    response = upload(client, user, make_image_bytes(size=(256, 256)))

    assert response.status_code == 413


def test_upload_requires_login(client: TestClient) -> None:
    response = client.post(IMAGES_URL, files={"file": ("photo.jpg", make_image_bytes(), "image/jpeg")})

    assert response.status_code == 401


def test_media_served_as_webp(
    client: TestClient, create_user: Callable[..., AuthedUser], storage: LocalStorage, monkeypatch
) -> None:
    user = create_user()
    url = upload(client, user, make_image_bytes()).json()["url"]
    # Point the /media mount at the test storage directory.
    media_mount = next(route for route in client.app.routes if getattr(route, "name", "") == "media")
    monkeypatch.setattr(media_mount.app, "directory", str(storage.root))
    monkeypatch.setattr(media_mount.app, "all_directories", [str(storage.root)])

    response = client.get(url.removeprefix("http://localhost:8000"))

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
