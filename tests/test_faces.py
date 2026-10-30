import io
import uuid
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors
from PIL import Image
from sqlalchemy.orm import Session

from app.faces import Face, Faces, FaceLocatorUnavailableError, GeminiFaceLocator, get_face_locator
from app.main import app
from app.models.image import Image as ImageModel
from app.storage import LocalStorage
from tests.conftest import AuthedUser

IMAGES_URL = "/api/v1/images"
FACE = [250, 250, 750, 750]


class FakeLocator:
    def __init__(self, boxes: list[list[int]] | None = None, error: Exception | None = None) -> None:
        self.boxes = [FACE] if boxes is None else boxes
        self.error = error
        self.calls = 0

    def locate(self, image_jpeg: bytes) -> list[list[int]]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.boxes


def use_locator(fake: FakeLocator) -> FakeLocator:
    app.dependency_overrides[get_face_locator] = lambda: fake
    return fake


def checkerboard(size: int = 200, square: int = 10) -> bytes:
    """A sharp pattern, so blurring visibly changes it."""
    image = Image.new("RGB", (size, size), "white")
    for y in range(0, size, square):
        for x in range(0, size, square):
            if (x // square + y // square) % 2:
                image.paste((0, 0, 0), (x, y, x + square, y + square))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def upload(client: TestClient, user: AuthedUser, data: bytes) -> dict:
    response = client.post(
        IMAGES_URL, headers=user.headers, files={"file": ("photo.png", data, "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()


def blur(client: TestClient, user: AuthedUser, image_id: str):
    return client.post(f"{IMAGES_URL}/{image_id}/blur-faces", headers=user.headers)


def stored(storage: LocalStorage, image: dict) -> Image.Image:
    key = image["url"][image["url"].index("images/"):]
    return Image.open(io.BytesIO(storage.read(key))).convert("RGB")


def spread(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    """Difference between the darkest and lightest pixel in a region."""
    low, high = image.crop(box).convert("L").getextrema()
    return high - low


# --- endpoint ----------------------------------------------------------------------------


def test_blur_faces_makes_a_blurred_copy(
    client: TestClient, create_user: Callable[..., AuthedUser], storage: LocalStorage
) -> None:
    locator = use_locator(FakeLocator())
    user = create_user()
    original = upload(client, user, checkerboard())

    response = blur(client, user, original["id"])

    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["id"] != original["id"]
    assert (copy["width"], copy["height"]) == (original["width"], original["height"])
    assert copy["generated"] is False
    assert locator.calls == 1

    before, after = stored(storage, original), stored(storage, copy)
    center = (80, 80, 120, 120)  # inside the face box
    corner = (0, 0, 20, 20)  # well outside it
    assert spread(before, center) > 200
    assert spread(after, center) < 60
    assert spread(after, corner) > 200
    # The original is untouched.
    assert spread(stored(storage, original), center) > 200


def test_blurred_try_on_stays_labeled_ai(
    client: TestClient, create_user: Callable[..., AuthedUser], db: Session
) -> None:
    use_locator(FakeLocator())
    user = create_user()
    original = upload(client, user, checkerboard())
    db.get(ImageModel, uuid.UUID(original["id"])).generated = True
    db.commit()

    response = blur(client, user, original["id"])

    assert response.status_code == 201, response.text
    assert response.json()["generated"] is True


def test_no_face_found_is_422(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    use_locator(FakeLocator(boxes=[]))
    user = create_user()
    original = upload(client, user, checkerboard())

    response = blur(client, user, original["id"])

    assert response.status_code == 422
    assert response.json()["detail"] == "No face found in this photo"


def test_someone_elses_image_is_404(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    locator = use_locator(FakeLocator())
    owner, other = create_user("owner"), create_user("other")
    image_id = upload_image(owner)

    response = blur(client, other, image_id)

    assert response.status_code == 404
    assert locator.calls == 0


def test_unknown_image_is_404(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    use_locator(FakeLocator())
    user = create_user()

    response = blur(client, user, "00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


def test_locator_unavailable_is_503(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    use_locator(FakeLocator(error=FaceLocatorUnavailableError("Face blurring is temporarily unavailable")))
    user = create_user()

    response = blur(client, user, upload_image(user))

    assert response.status_code == 503
    assert response.json()["detail"] == "Face blurring is temporarily unavailable"


def test_blur_requires_login(client: TestClient) -> None:
    response = client.post(f"{IMAGES_URL}/00000000-0000-0000-0000-000000000000/blur-faces")

    assert response.status_code == 401


# --- talking to Google -------------------------------------------------------------------


def stub_client(result: object = None, error: Exception | None = None):
    def generate_content(**kwargs):
        if error:
            raise error
        return result

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def test_gemini_returns_valid_boxes_only() -> None:
    parsed = Faces(faces=[Face(box_2d=FACE), Face(box_2d=[500, 500, 400, 600]), Face(box_2d=[1, 2, 3])])
    locator = GeminiFaceLocator(stub_client(SimpleNamespace(parsed=parsed)), "gemini-3.1-flash-lite")

    assert locator.locate(b"jpeg") == [FACE]


def test_gemini_unparseable_output_is_no_faces() -> None:
    locator = GeminiFaceLocator(stub_client(SimpleNamespace(parsed=None)), "gemini-3.1-flash-lite")

    assert locator.locate(b"jpeg") == []


def test_gemini_rejected_photo_is_no_faces() -> None:
    error = errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}})
    locator = GeminiFaceLocator(stub_client(error=error), "gemini-3.1-flash-lite")

    assert locator.locate(b"jpeg") == []


@pytest.mark.parametrize("code", [403, 429])
def test_gemini_client_errors_are_unavailable(code: int) -> None:
    error = errors.ClientError(code, {"error": {"code": code}})
    locator = GeminiFaceLocator(stub_client(error=error), "gemini-3.1-flash-lite")

    with pytest.raises(FaceLocatorUnavailableError):
        locator.locate(b"jpeg")
