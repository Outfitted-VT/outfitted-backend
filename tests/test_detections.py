from collections.abc import Callable
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors

from app.core.config import settings
from app.garments import (
    Detection,
    DetectedPiece,
    DetectionUnavailableError,
    GeminiGarmentDetector,
    get_garment_detector,
)
from app.main import app
from app.shopping import NoProductFinder, get_product_finder
from tests.conftest import AuthedUser

DETECTIONS_URL = "/api/v1/detections"
FITS_URL = "/api/v1/fits"

TANK = DetectedPiece(
    category="top", name="ribbed tank top", color="black", material="ribbed cotton",
    silhouette="fitted", box_2d=[200, 300, 600, 700],
)
SHORTS = DetectedPiece(category="bottom", name="drawstring sweat shorts", color="light blue")


class FakeDetector:
    def __init__(self, result: Detection | None = None, error: Exception | None = None) -> None:
        self.result = result or Detection(
            items=[TANK, SHORTS], occasion_tags=["Casual", "gym"], style_tags=["minimalist"]
        )
        self.error = error
        self.calls = 0

    def detect(self, image_jpeg: bytes) -> Detection:
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def use_detector(fake: FakeDetector) -> FakeDetector:
    app.dependency_overrides[get_garment_detector] = lambda: fake
    return fake


@pytest.fixture
def detector(client: TestClient) -> FakeDetector:
    return use_detector(FakeDetector())


@pytest.fixture(autouse=True)
def no_shop_matching(client: TestClient) -> None:
    # Never make real (paid) SerpApi searches from tests, even if a key is in .env.
    app.dependency_overrides[get_product_finder] = lambda: NoProductFinder()


def detect(client: TestClient, user: AuthedUser, image_id: str):
    return client.post(DETECTIONS_URL, headers=user.headers, json={"image_id": image_id})


# --- endpoint ----------------------------------------------------------------------------


def test_detection_suggests_items_and_tags(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    detector: FakeDetector,
) -> None:
    user = create_user()
    image_id = upload_image(user)

    response = detect(client, user, image_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["image_id"] == image_id
    assert body["model"] == settings.DETECTION_MODEL
    assert body["occasion_tags"] == ["casual", "gym"]
    assert body["style_tags"] == ["minimalist"]
    tank, shorts = body["items"]
    assert tank == {
        "category": "top",
        "name": "ribbed tank top",
        "brand": None,
        "color": "black",
        "pattern": None,
        "material": "ribbed cotton",
        "silhouette": "fitted",
        "url": None,
        # The center of the box [ymin=200, xmin=300, ymax=600, xmax=700] out of 1000.
        "pin": {"image_id": image_id, "x": 0.5, "y": 0.4},
        "source": "detected",
        "matches": [],
    }
    assert shorts["pin"] is None
    assert shorts["source"] == "detected"


def test_detected_items_can_be_posted_as_a_fit(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    detector: FakeDetector,
) -> None:
    user = create_user()
    image_id = upload_image(user)
    detection = detect(client, user, image_id).json()

    response = client.post(
        FITS_URL,
        headers=user.headers,
        json={
            "image_ids": [image_id],
            "items": detection["items"],
            "occasion_tags": detection["occasion_tags"],
            "style_tags": detection["style_tags"],
        },
    )

    assert response.status_code == 201, response.text
    fit = response.json()
    assert [item["name"] for item in fit["items"]] == ["ribbed tank top", "drawstring sweat shorts"]
    assert fit["items"][0]["source"] == "detected"
    assert fit["items"][0]["material"] == "ribbed cotton"
    assert fit["items"][0]["pin"] == {"image_id": image_id, "x": 0.5, "y": 0.4}
    assert fit["occasion_tags"] == ["casual", "gym"]
    assert fit["style_tags"] == ["minimalist"]


def test_repeat_detection_is_cached(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    detector: FakeDetector,
) -> None:
    user = create_user()
    image_id = upload_image(user)
    first = detect(client, user, image_id).json()

    second = detect(client, user, image_id)

    assert second.status_code == 200
    assert second.json() == first
    assert detector.calls == 1


def test_detection_rejects_someone_elses_image(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    detector: FakeDetector,
) -> None:
    user, other = create_user("jane"), create_user("bob")

    response = detect(client, user, upload_image(other))

    assert response.status_code == 400
    assert response.json() == {"detail": "Image not found"}
    assert detector.calls == 0


def test_daily_limit_applies_to_new_images_only(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    detector: FakeDetector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DETECTION_DAILY_LIMIT", 1)
    user = create_user()
    first = upload_image(user)
    assert detect(client, user, first).status_code == 200

    assert detect(client, user, upload_image(user)).status_code == 429
    # The already-detected image is still served from storage.
    assert detect(client, user, first).status_code == 200
    assert detector.calls == 1


def test_unavailable_returns_503(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
) -> None:
    use_detector(FakeDetector(error=DetectionUnavailableError("Piece detection is temporarily unavailable")))
    user = create_user()

    response = detect(client, user, upload_image(user))

    assert response.status_code == 503
    assert response.json() == {"detail": "Piece detection is temporarily unavailable"}


def test_not_configured_returns_503(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLOUD_PROJECT", None)
    user = create_user()

    response = detect(client, user, upload_image(user))

    assert response.status_code == 503
    assert response.json() == {"detail": "Piece detection isn't set up on this server"}


def test_model_output_is_cleaned_up(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
) -> None:
    messy = Detection(
        items=[
            DetectedPiece(category="shoes", name="  chunky   loafers ", color="x" * 80, box_2d=[900, 100, 800, 200]),
            DetectedPiece(category="bag", name="", box_2d=[1, 2, 3]),
            *[DetectedPiece(category="jewelry", name=f"ring {i}") for i in range(40)],
        ],
        occasion_tags=["Date  Night", "date night", "", "x" * 50],
        style_tags=[f"style {i}" for i in range(20)],
    )
    use_detector(FakeDetector(result=messy))
    user = create_user()

    body = detect(client, user, upload_image(user)).json()

    loafers, bag = body["items"][:2]
    assert loafers["name"] == "chunky loafers"
    assert len(loafers["color"]) == 50
    assert loafers["pin"] is None  # ymax < ymin
    assert bag["name"] == "bag"  # empty name falls back to the category
    assert bag["pin"] is None  # not a 4-number box
    assert len(body["items"]) == 30
    assert body["occasion_tags"] == ["date night", "x" * 30]
    assert len(body["style_tags"]) == 10


def test_empty_detection_is_not_an_error(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
) -> None:
    use_detector(FakeDetector(result=Detection()))
    user = create_user()

    response = detect(client, user, upload_image(user))

    assert response.status_code == 200
    assert response.json()["items"] == []


# --- talking to Google -------------------------------------------------------------------


def stub_client(result: object = None, error: Exception | None = None):
    def generate_content(**kwargs):
        if error:
            raise error
        return result

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def test_gemini_returns_parsed_detection() -> None:
    parsed = Detection(items=[TANK], style_tags=["minimalist"])
    detector = GeminiGarmentDetector(stub_client(SimpleNamespace(parsed=parsed)), "gemini-3.1-flash-lite")

    assert detector.detect(b"jpeg") == parsed


def test_gemini_unparseable_output_is_empty() -> None:
    detector = GeminiGarmentDetector(stub_client(SimpleNamespace(parsed=None)), "gemini-3.1-flash-lite")

    assert detector.detect(b"jpeg") == Detection()


def test_gemini_rejected_photo_is_empty() -> None:
    error = errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}})
    detector = GeminiGarmentDetector(stub_client(error=error), "gemini-3.1-flash-lite")

    assert detector.detect(b"jpeg") == Detection()


@pytest.mark.parametrize("code", [403, 429])
def test_gemini_client_errors_are_unavailable(code: int) -> None:
    error = errors.ClientError(code, {"error": {"code": code}})
    detector = GeminiGarmentDetector(stub_client(error=error), "gemini-3.1-flash-lite")

    with pytest.raises(DetectionUnavailableError):
        detector.detect(b"jpeg")


def test_gemini_server_error_is_unavailable() -> None:
    error = errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})
    detector = GeminiGarmentDetector(stub_client(error=error), "gemini-3.1-flash-lite")

    with pytest.raises(DetectionUnavailableError):
        detector.detect(b"jpeg")
