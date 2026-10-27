import io
import uuid
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors
from PIL import Image
from sqlalchemy.orm import Session

from app import tryon as tryon_module
from app.core.config import settings
from app.core.images import to_jpeg
from app.main import app
from app.models.image import Image as ImageModel
from app.models.tryon import TryOn
from app.schemas.tryon import PieceSlot
from app.tryon import (
    GEMINI_PROMPT,
    SLOT_DESCRIPTIONS,
    Garment,
    GeminiImageGenerator,
    TryOnBlockedError,
    TryOnUnavailableError,
    TryOnUnsupportedError,
    UnavailableGenerator,
    VirtualTryOnGenerator,
    get_tryon_generator,
)
from tests.conftest import AuthedUser, make_image_bytes

TRYONS_URL = "/api/v1/tryons"
FITS_URL = "/api/v1/fits"


class FakeGenerator:
    """Stands in for Google: records its inputs and returns a fixed image, or raises."""

    def __init__(
        self, result: bytes | None = None, error: Exception | None = None, max_garments: int = 7
    ) -> None:
        self.result = result if result is not None else make_image_bytes("PNG", size=(40, 60))
        self.error = error
        self.max_garments = max_garments
        self.calls: list[tuple[bytes, list[Garment]]] = []

    def generate(self, person_jpeg: bytes, garments: list[Garment]) -> bytes:
        self.calls.append((person_jpeg, garments))
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
    [(person_jpeg, [outfit])] = generator.calls
    assert Image.open(io.BytesIO(person_jpeg)).format == "JPEG"
    assert Image.open(io.BytesIO(outfit.jpeg)).format == "JPEG"
    assert outfit.slot is None


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

    assert generator.generate(b"person", [Garment(b"outfit")]) == b"png-bytes"


def test_gemini_without_image_is_blocked() -> None:
    response = gemini_response(finish_reason="IMAGE_SAFETY")
    generator = GeminiImageGenerator(stub_client("generate_content", response), "gemini-3.1-flash-image")

    with pytest.raises(TryOnBlockedError):
        generator.generate(b"person", [Garment(b"outfit")])


def test_virtual_try_on_returns_generated_image() -> None:
    response = SimpleNamespace(
        generated_images=[SimpleNamespace(image=SimpleNamespace(image_bytes=b"png-bytes"))]
    )
    generator = VirtualTryOnGenerator(stub_client("recontext_image", response), "virtual-try-on-001")

    assert generator.generate(b"person", [Garment(b"outfit")]) == b"png-bytes"


def test_virtual_try_on_filtered_is_blocked() -> None:
    response = SimpleNamespace(
        generated_images=[SimpleNamespace(image=None, rai_filtered_reason="filtered")]
    )
    generator = VirtualTryOnGenerator(stub_client("recontext_image", response), "virtual-try-on-001")

    with pytest.raises(TryOnBlockedError):
        generator.generate(b"person", [Garment(b"outfit")])


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
        generator.generate(b"person", [Garment(b"outfit")])


# --- input conversion ----------------------------------------------------------------------


def test_to_jpeg_puts_transparent_areas_on_white() -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(buffer, format="WEBP")

    converted = Image.open(io.BytesIO(to_jpeg(buffer.getvalue())))

    assert converted.format == "JPEG"
    r, g, b = converted.getpixel((5, 5))
    assert min(r, g, b) > 240


# --- pieces mode ---------------------------------------------------------------------------


def try_on_pieces(client: TestClient, user: AuthedUser, person_id: str, pieces: dict[str, str]):
    return client.post(
        TRYONS_URL,
        headers=user.headers,
        json={
            "person_image_id": person_id,
            "pieces": [{"slot": slot, "image_id": image_id} for slot, image_id in pieces.items()],
        },
    )


def test_whole_outfit_response_shape(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
) -> None:
    user = create_user()

    body = try_on(client, user, upload_image(user), upload_image(user)).json()

    assert body["mode"] == "outfit"
    assert body["pieces"] == []


def test_pieces_tryon(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
) -> None:
    user = create_user()
    person = upload_image(user)
    pieces = {"top": upload_image(user), "bottom": upload_image(user), "feet": upload_image(user)}

    response = try_on_pieces(client, user, person, pieces)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mode"] == "pieces"
    assert body["outfit_image"] is None
    assert [(p["slot"], p["image"]["id"]) for p in body["pieces"]] == list(pieces.items())
    assert body["result_image"]["generated"] is True
    [(_, garments)] = generator.calls
    assert [g.slot for g in garments] == ["top", "bottom", "feet"]
    assert all(Image.open(io.BytesIO(g.jpeg)).format == "JPEG" for g in garments)


def test_pieces_are_sent_head_to_toe(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
) -> None:
    user = create_user()
    person = upload_image(user)
    # Sent in a scrambled order.
    pieces = {
        "feet": upload_image(user),
        "head": upload_image(user),
        "accessory": upload_image(user),
        "outerwear": upload_image(user),
        "top": upload_image(user),
    }

    body = try_on_pieces(client, user, person, pieces).json()

    expected = ["head", "top", "outerwear", "feet", "accessory"]
    assert [g.slot for g in generator.calls[0][1]] == expected
    assert [p["slot"] for p in body["pieces"]] == expected
    # Each slot keeps its own image.
    assert {p["slot"]: p["image"]["id"] for p in body["pieces"]} == pieces


def test_single_piece_is_allowed(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
) -> None:
    user = create_user()

    response = try_on_pieces(client, user, upload_image(user), {"feet": upload_image(user)})

    assert response.status_code == 201
    assert [g.slot for g in generator.calls[0][1]] == ["feet"]


def _invalid_bodies(person: str, a: str, b: str) -> dict[str, dict]:
    def pieces(*items: tuple[str, str]) -> dict:
        return {
            "person_image_id": person,
            "pieces": [{"slot": slot, "image_id": image_id} for slot, image_id in items],
        }

    return {
        "neither mode": {"person_image_id": person},
        "both modes": {**pieces(("top", b)), "outfit_image_id": a},
        "no pieces": pieces(),
        "duplicate slot": pieces(("top", a), ("top", b)),
        "same image twice": pieces(("top", a), ("bottom", a)),
        "one_piece with top": pieces(("one_piece", a), ("top", b)),
        "one_piece with bottom": pieces(("one_piece", a), ("bottom", b)),
        "unknown slot": pieces(("hands", a)),
    }


@pytest.mark.parametrize(
    "reason",
    [
        "neither mode",
        "both modes",
        "no pieces",
        "duplicate slot",
        "same image twice",
        "one_piece with top",
        "one_piece with bottom",
        "unknown slot",
    ],
)
def test_invalid_requests(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
    reason: str,
) -> None:
    user = create_user()
    body = _invalid_bodies(upload_image(user), upload_image(user), upload_image(user))[reason]

    response = client.post(TRYONS_URL, headers=user.headers, json=body)

    assert response.status_code == 422, reason
    assert generator.calls == []


def test_one_piece_with_outerwear_and_shoes_is_fine(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
) -> None:
    user = create_user()
    pieces = {"one_piece": upload_image(user), "outerwear": upload_image(user), "feet": upload_image(user)}

    assert try_on_pieces(client, user, upload_image(user), pieces).status_code == 201


def test_piece_must_be_your_image(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
) -> None:
    user, other = create_user("jane"), create_user("bob")

    response = try_on_pieces(
        client, user, upload_image(user), {"top": upload_image(user), "feet": upload_image(other)}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Image not found"}
    assert generator.calls == []


def test_model_that_takes_one_photo_rejects_pieces(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TRYON_DAILY_LIMIT", 1)
    fake = FakeGenerator(max_garments=1)
    use_generator(fake)
    user = create_user()
    person = upload_image(user)

    response = try_on_pieces(client, user, person, {"top": upload_image(user), "feet": upload_image(user)})

    assert response.status_code == 400
    assert "one photo" in response.json()["detail"]
    assert fake.calls == []
    # Rejected requests don't use up the daily limit.
    assert try_on(client, user, person, upload_image(user)).status_code == 201


def test_deleted_piece_image_shows_as_null(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    generator: FakeGenerator,
    db: Session,
) -> None:
    user = create_user()
    top = upload_image(user)
    tryon_id = try_on_pieces(client, user, upload_image(user), {"top": top}).json()["id"]

    db.delete(db.get(ImageModel, uuid.UUID(top)))
    db.commit()
    db.expire_all()

    tryon = db.get(TryOn, uuid.UUID(tryon_id))
    assert [(piece.slot, piece.image) for piece in tryon.pieces] == [("top", None)]


# --- what Gemini receives ------------------------------------------------------------------


def recording_gemini() -> tuple[GeminiImageGenerator, list[dict]]:
    """A Gemini generator whose fake client records each call's arguments."""
    calls: list[dict] = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        return gemini_response(SimpleNamespace(inline_data=SimpleNamespace(data=b"png-bytes")))

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return GeminiImageGenerator(client, "gemini-3.1-flash-image"), calls


def describe(contents: list) -> list[str]:
    """Contents as text, with each image shown as <its bytes>."""
    return [part if isinstance(part, str) else f"<{part.inline_data.data.decode()}>" for part in contents]


def test_gemini_whole_outfit_request_is_unchanged() -> None:
    generator, calls = recording_gemini()

    generator.generate(b"person", [Garment(b"outfit")])

    assert describe(calls[0]["contents"]) == ["<person>", "<outfit>", GEMINI_PROMPT]


def test_gemini_pieces_are_labeled_in_order() -> None:
    generator, calls = recording_gemini()

    generator.generate(b"person", [Garment(b"tee", "top"), Garment(b"sneakers", "feet")])

    contents = describe(calls[0]["contents"])
    assert contents[0] == "<person>"
    assert contents[2:6] == [
        "Image 2 is a top (such as a shirt, t-shirt, or sweater) for the upper body:",
        "<tee>",
        "Image 3 is footwear (shoes):",
        "<sneakers>",
    ]
    assert "wearing all of these items together" in contents[-1]


def test_every_slot_has_a_description() -> None:
    assert set(SLOT_DESCRIPTIONS) == {slot.value for slot in PieceSlot}


def test_virtual_try_on_rejects_several_garments() -> None:
    generator = VirtualTryOnGenerator(stub_client("recontext_image"), "virtual-try-on-001")

    with pytest.raises(TryOnUnsupportedError):
        generator.generate(b"person", [Garment(b"tee", "top"), Garment(b"shoes", "feet")])
