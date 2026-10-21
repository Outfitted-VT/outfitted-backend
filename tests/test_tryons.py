import io
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors
from PIL import Image

from app import tryon as tryon_module
from app.core.config import settings
from app.core.images import to_jpeg
from app.main import app
from app.tryon import (
    GeminiImageGenerator,
    TryOnBlockedError,
    TryOnUnavailableError,
    UnavailableGenerator,
    VirtualTryOnGenerator,
    get_tryon_generator,
)
from tests.conftest import AuthedUser, make_image_bytes

TRYONS_URL = "/api/v1/tryons"
FITS_URL = "/api/v1/fits"


class FakeGenerator:
    """Stands in for Google: records its inputs and returns a fixed image, or raises."""

    def __init__(self, result: bytes | None = None, error: Exception | None = None) -> None:
        self.result = result if result is not None else make_image_bytes("PNG", size=(40, 60))
        self.error = error
        self.calls: list[tuple[bytes, bytes]] = []

    def generate(self, person_jpeg: bytes, outfit_jpeg: bytes) -> bytes:
        self.calls.append((person_jpeg, outfit_jpeg))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def generator(client: TestClient) -> FakeGenerator:
    fake = FakeGenerator()
    app.dependency_overrides[get_tryon_generator] = lambda: fake
    return fake


def use_generator(fake: FakeGenerator) -> None:
    app.dependency_overrides[get_tryon_generator] = lambda: fake


def try_on(client: TestClient, user: AuthedUser, person_id: str, outfit_id: str):
    return client.post(
        TRYONS_URL,
        headers=user.headers,
        json={"person_image_id": person_id, "outfit_image_id": outfit_id},
    )


# --- endpoint ----------------------------------------------------------------------------


def test_tryon_returns_generated_image_owned_by_user(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
) -> None:
    user = create_user()
    person, outfit = upload_image(user), upload_image(user)

    response = try_on(client, user, person, outfit)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["person_image"]["id"] == person
    assert body["outfit_image"]["id"] == outfit
    assert body["model"] == settings.TRYON_MODEL
    result = body["result_image"]
    assert result["generated"] is True
    assert (result["width"], result["height"]) == (40, 60)
    assert result["url"].endswith(".webp")
    assert body["person_image"]["generated"] is False


def test_generator_receives_jpegs(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
) -> None:
    user = create_user()

    try_on(client, user, upload_image(user), upload_image(user))

    # Uploads are stored as WebP; the models only accept JPEG or PNG.
    [(person_jpeg, outfit_jpeg)] = generator.calls
    assert Image.open(io.BytesIO(person_jpeg)).format == "JPEG"
    assert Image.open(io.BytesIO(outfit_jpeg)).format == "JPEG"


def test_result_can_be_posted_as_a_fit(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
) -> None:
    user = create_user()
    result_id = try_on(client, user, upload_image(user), upload_image(user)).json()["result_image"]["id"]

    response = client.post(
        FITS_URL, headers=user.headers, json={"image_ids": [result_id], "caption": "Tried it on"}
    )

    assert response.status_code == 201, response.text
    assert response.json()["images"][0]["generated"] is True


def test_tryon_rejects_someone_elses_image(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
) -> None:
    user, other = create_user("jane"), create_user("bob")

    response = try_on(client, user, upload_image(user), upload_image(other))

    assert response.status_code == 400
    assert response.json() == {"detail": "Image not found"}
    assert generator.calls == []


def test_tryon_requires_login(client: TestClient) -> None:
    response = client.post(
        TRYONS_URL,
        json={
            "person_image_id": "517830fe-d102-41c1-84b5-f7036e814611",
            "outfit_image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26",
        },
    )

    assert response.status_code == 401


def test_daily_limit(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TRYON_DAILY_LIMIT", 1)
    user, other = create_user("jane"), create_user("bob")
    person, outfit = upload_image(user), upload_image(user)
    assert try_on(client, user, person, outfit).status_code == 201

    response = try_on(client, user, person, outfit)

    assert response.status_code == 429
    assert len(generator.calls) == 1
    # The limit is per user.
    assert try_on(client, other, upload_image(other), upload_image(other)).status_code == 201


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (TryOnBlockedError("We couldn't create a try-on from these photos"), 422),
        (TryOnUnavailableError("Try-on is temporarily unavailable"), 503),
    ],
)
def test_generator_errors(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    error: Exception,
    status_code: int,
) -> None:
    use_generator(FakeGenerator(error=error))
    user = create_user()

    response = try_on(client, user, upload_image(user), upload_image(user))

    assert response.status_code == status_code
    assert response.json() == {"detail": str(error)}


def test_failed_tryon_does_not_count_toward_limit(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TRYON_DAILY_LIMIT", 1)
    user = create_user()
    person, outfit = upload_image(user), upload_image(user)
    use_generator(FakeGenerator(error=TryOnUnavailableError("Try-on is temporarily unavailable")))
    try_on(client, user, person, outfit)

    use_generator(FakeGenerator())

    assert try_on(client, user, person, outfit).status_code == 201


def test_unreadable_result_is_reported_as_blocked(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
) -> None:
    use_generator(FakeGenerator(result=b"not an image"))
    user = create_user()

    response = try_on(client, user, upload_image(user), upload_image(user))

    assert response.status_code == 422


def test_not_configured_returns_503(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLOUD_PROJECT", None)
    user = create_user()

    response = try_on(client, user, upload_image(user), upload_image(user))

    assert response.status_code == 503
    assert response.json() == {"detail": "Try-on isn't set up on this server"}


# --- choosing the model ------------------------------------------------------------------


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> object:
    client = object()
    monkeypatch.setattr(settings, "GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setattr(tryon_module, "_make_client", lambda: client)
    tryon_module._build_generator.cache_clear()
    yield client
    tryon_module._build_generator.cache_clear()


def test_gemini_is_the_default_model(fake_client: object) -> None:
    generator = get_tryon_generator()

    assert isinstance(generator, GeminiImageGenerator)
    assert generator.model == "gemini-3.1-flash-image"
    assert settings.tryon_location == "global"


def test_virtual_try_on_model_can_be_selected(
    fake_client: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TRYON_MODEL", "virtual-try-on-001")

    generator = get_tryon_generator()

    assert isinstance(generator, VirtualTryOnGenerator)
    assert settings.tryon_location == "us-central1"


def test_client_creation_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLOUD_PROJECT", "test-project")
    tryon_module._build_generator.cache_clear()

    def no_credentials() -> object:
        raise RuntimeError("no credentials")

    monkeypatch.setattr(tryon_module, "_make_client", no_credentials)
    assert isinstance(get_tryon_generator(), UnavailableGenerator)

    monkeypatch.setattr(tryon_module, "_make_client", lambda: object())
    assert isinstance(get_tryon_generator(), GeminiImageGenerator)
    tryon_module._build_generator.cache_clear()


# --- talking to Google -------------------------------------------------------------------


def stub_client(method: str, result: object = None, error: Exception | None = None):
    """An object shaped like genai.Client whose models.<method> returns result or raises."""

    def call(**kwargs):
        if error:
            raise error
        return result

    return SimpleNamespace(models=SimpleNamespace(**{method: call}))


def gemini_response(*parts: object, finish_reason: str = "STOP") -> object:
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(content=SimpleNamespace(parts=list(parts)), finish_reason=finish_reason)
        ],
        prompt_feedback=None,
    )


def test_gemini_returns_the_image_part() -> None:
    response = gemini_response(
        SimpleNamespace(inline_data=None, text="Here you go"),
        SimpleNamespace(inline_data=SimpleNamespace(data=b"png-bytes")),
    )
    generator = GeminiImageGenerator(stub_client("generate_content", response), "gemini-3.1-flash-image")

    assert generator.generate(b"person", b"outfit") == b"png-bytes"


def test_gemini_without_image_is_blocked() -> None:
    response = gemini_response(finish_reason="IMAGE_SAFETY")
    generator = GeminiImageGenerator(stub_client("generate_content", response), "gemini-3.1-flash-image")

    with pytest.raises(TryOnBlockedError):
        generator.generate(b"person", b"outfit")


def test_virtual_try_on_returns_generated_image() -> None:
    response = SimpleNamespace(
        generated_images=[SimpleNamespace(image=SimpleNamespace(image_bytes=b"png-bytes"))]
    )
    generator = VirtualTryOnGenerator(stub_client("recontext_image", response), "virtual-try-on-001")

    assert generator.generate(b"person", b"outfit") == b"png-bytes"


def test_virtual_try_on_filtered_is_blocked() -> None:
    response = SimpleNamespace(
        generated_images=[SimpleNamespace(image=None, rai_filtered_reason="filtered")]
    )
    generator = VirtualTryOnGenerator(stub_client("recontext_image", response), "virtual-try-on-001")

    with pytest.raises(TryOnBlockedError):
        generator.generate(b"person", b"outfit")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}), TryOnUnavailableError),
        (errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}}), TryOnBlockedError),
        (errors.ClientError(403, {"error": {"code": 403, "status": "PERMISSION_DENIED"}}), TryOnUnavailableError),
        (errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}}), TryOnUnavailableError),
    ],
)
def test_google_errors_are_translated(error: Exception, expected: type[Exception]) -> None:
    generator = GeminiImageGenerator(stub_client("generate_content", error=error), "gemini-3.1-flash-image")

    with pytest.raises(expected):
        generator.generate(b"person", b"outfit")


# --- input conversion ----------------------------------------------------------------------


def test_to_jpeg_puts_transparent_areas_on_white() -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(buffer, format="WEBP")

    converted = Image.open(io.BytesIO(to_jpeg(buffer.getvalue())))

    assert converted.format == "JPEG"
    r, g, b = converted.getpixel((5, 5))
    assert min(r, g, b) > 240
