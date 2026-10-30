"""Shop links for detected pieces (Google Lens via SerpApi)."""

import io
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.core.images import crop_jpeg
from app.garments import Detection, DetectedPiece, get_garment_detector
from app.main import app
from app.shopping import (
    NoProductFinder,
    ProductMatch,
    SerpApiLensFinder,
    get_product_finder,
    parse_matches,
)
from tests.conftest import AuthedUser, make_image_bytes

DETECTIONS_URL = "/api/v1/detections"
FITS_URL = "/api/v1/fits"

TOP = DetectedPiece(
    category="top", name="ribbed tank top", color="black", material="cotton", box_2d=[200, 300, 600, 700]
)
SHORTS = DetectedPiece(category="bottom", name="sweat shorts", box_2d=[600, 250, 1000, 750])
UNLOCATED = DetectedPiece(category="shoes", name="sneakers")

JACKET = ProductMatch(title="Ribbed Tank", link="https://shop.example/tank", source="Shop", price="$20")
OTHER = ProductMatch(title="Tank Top", link="https://other.example/tank", source="Other")


class FakeDetector:
    def __init__(self, items: list[DetectedPiece]) -> None:
        self.items = items

    def detect(self, image_jpeg: bytes) -> Detection:
        return Detection(items=self.items)


class FakeFinder:
    def __init__(self, matches: list[ProductMatch]) -> None:
        self.matches = matches
        self.crops: list[bytes] = []
        self.descriptions: list[str] = []

    def find(self, crop_jpeg: bytes, description: str) -> list[ProductMatch]:
        self.crops.append(crop_jpeg)
        self.descriptions.append(description)
        return self.matches


def setup(items: list[DetectedPiece], matches: list[ProductMatch]) -> FakeFinder:
    finder = FakeFinder(matches)
    app.dependency_overrides[get_garment_detector] = lambda: FakeDetector(items)
    app.dependency_overrides[get_product_finder] = lambda: finder
    return finder


def detect(client: TestClient, user: AuthedUser, image_id: str) -> dict:
    response = client.post(DETECTIONS_URL, headers=user.headers, json={"image_id": image_id})
    assert response.status_code == 200, response.text
    return response.json()


# --- attaching matches -------------------------------------------------------------------


def test_located_pieces_get_the_best_match_as_their_link(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    finder = setup([TOP, UNLOCATED], [JACKET, OTHER])
    user = create_user()

    top, sneakers = detect(client, user, upload_image(user))["items"]

    assert top["url"] == "https://shop.example/tank"
    assert [m["link"] for m in top["matches"]] == [JACKET.link, OTHER.link]
    assert top["matches"][0] == {
        "title": "Ribbed Tank", "link": JACKET.link, "source": "Shop", "thumbnail": None, "price": "$20"
    }
    # Pieces the model didn't locate can't be cropped, so they aren't searched.
    assert sneakers["url"] is None
    assert sneakers["matches"] == []
    assert len(finder.crops) == 1


def test_finder_gets_a_small_jpeg_crop(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    finder = setup([TOP], [JACKET])
    user = create_user()

    detect(client, user, upload_image(user))

    crop = Image.open(io.BytesIO(finder.crops[0]))
    assert crop.format == "JPEG"
    assert len(finder.crops[0]) < 500 * 1024
    # The piece's description is passed along to rank the lookalikes.
    assert finder.descriptions == ["black cotton ribbed tank top"]


def test_no_matches_means_no_link(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    setup([TOP], [])
    user = create_user()

    [top] = detect(client, user, upload_image(user))["items"]

    assert top["url"] is None
    assert top["matches"] == []


def test_matching_is_capped_per_photo(
    client: TestClient,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SHOP_MATCH_MAX_ITEMS", 1)
    finder = setup([TOP, SHORTS], [JACKET])
    user = create_user()

    top, shorts = detect(client, user, upload_image(user))["items"]

    assert top["url"] == JACKET.link
    assert shorts["url"] is None
    assert len(finder.crops) == 1


def test_matches_are_cached_with_the_detection(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    finder = setup([TOP], [JACKET])
    user = create_user()
    image_id = upload_image(user)
    first = detect(client, user, image_id)

    assert detect(client, user, image_id) == first
    assert len(finder.crops) == 1


def test_detected_item_with_matches_can_be_posted(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    setup([TOP], [JACKET, OTHER])
    user = create_user()
    image_id = upload_image(user)
    [top] = detect(client, user, image_id)["items"]

    # The app sends the item back as-is; `matches` is ignored.
    response = client.post(FITS_URL, headers=user.headers, json={"image_ids": [image_id], "items": [top]})

    assert response.status_code == 201, response.text
    item = response.json()["items"][0]
    assert item["url"] == "https://shop.example/tank"
    assert "matches" not in item


# --- parsing and calling SerpApi ---------------------------------------------------------


def test_parse_matches_prefers_priced_product_pages() -> None:
    results = {
        "visual_matches": [
            {"title": "Blog post", "link": "https://blog.example/post"},
            {"title": "No link"},
            {"title": "Bad link", "link": "ftp://x.example/file"},
            {"title": "Product", "link": "https://shop.example/p", "source": "Shop",
             "thumbnail": "https://img.example/t.jpg", "price": {"value": "$39.90*", "extracted_value": 39.9}},
            {"title": "Image page", "link": "https://images.example/i"},
        ]
    }

    matches = parse_matches(results, "denim jacket", limit=2)

    assert [m.title for m in matches] == ["Product", "Blog post"]
    assert matches[0].price == "$39.90"  # the "*" Google adds is dropped
    assert matches[0].thumbnail == "https://img.example/t.jpg"


def test_parse_matches_ranks_by_description_then_google_order() -> None:
    # Real case: Lens put a cashmere tank first for a black ribbed tank top.
    results = {
        "visual_matches": [
            {"title": "Cashmere Tank (Men)", "link": "https://a.example/1", "price": {"value": "$495*"}},
            {"title": "Men's Black Ribbed Sleeveless Tank Top", "link": "https://b.example/2", "price": {"value": "$8*"}},
            {"title": "Black Tank", "link": "https://c.example/3", "price": {"value": "$12"}},
        ]
    }

    matches = parse_matches(results, "black cotton ribbed tank top", limit=3)

    assert [m.link for m in matches] == ["https://b.example/2", "https://c.example/3", "https://a.example/1"]


def test_parse_matches_tells_shorts_from_pants() -> None:
    results = {
        "visual_matches": [
            {"title": "Corduroy Cargo Pants", "link": "https://a.example/pants", "price": {"value": "$23"}},
            {"title": "Drawstring Cargo Shorts", "link": "https://b.example/shorts", "price": {"value": "$10"}},
        ]
    }

    matches = parse_matches(results, "light blue drawstring sweat short", limit=1)

    assert matches[0].link == "https://b.example/shorts"


def test_parse_matches_ranks_other_currencies_last() -> None:
    results = {
        "visual_matches": [
            {"title": "Rib Tank Top", "link": "https://shop.example.jp/tank", "price": {"value": "¥2,090*"}},
            {"title": "Rib Tank Top", "link": "https://blog.example/tank"},
            {"title": "Rib Tank Top", "link": "https://shop.example.com/tank", "price": {"value": "$20"}},
        ]
    }

    matches = parse_matches(results, "ribbed tank top", limit=3)

    assert [m.link for m in matches] == [
        "https://shop.example.com/tank",
        "https://blog.example/tank",
        "https://shop.example.jp/tank",
    ]


def test_parse_matches_ranks_the_wrong_color_last() -> None:
    # Real case: a green Hollister tee came first for a blue t-shirt.
    results = {
        "visual_matches": [
            {"title": "Mens T Shirt Green Short Sleeve Crew Neck", "link": "https://a.example/green", "price": {"value": "$13"}},
            {"title": "Classic Crew Neck T-Shirt", "link": "https://b.example/plain", "price": {"value": "$20"}},
            {"title": "Light Blue Crew Neck T-Shirt", "link": "https://c.example/blue", "price": {"value": "$18"}},
        ]
    }

    matches = parse_matches(results, "blue short sleeve crew neck t-shirt", limit=3)

    assert [m.link for m in matches] == [
        "https://c.example/blue",
        "https://b.example/plain",
        "https://a.example/green",
    ]


def test_parse_matches_ranks_unrelated_titles_last() -> None:
    # Real case: tapered pants from a store came second for a t-shirt.
    results = {
        "visual_matches": [
            {"title": "Tapered Pants 'Alen' in Anthracite", "link": "https://store.example/pants", "price": {"value": "$44"}},
            {"title": "Blue Short Sleeve Tee", "link": "https://www.poshmark.com/listing/1", "price": {"value": "$18"}},
        ]
    }

    matches = parse_matches(results, "blue short sleeve crew neck t-shirt", limit=2)

    assert [m.link for m in matches] == ["https://www.poshmark.com/listing/1", "https://store.example/pants"]


def test_parse_matches_drops_social_posts() -> None:
    # Real case: Facebook posts were offered as shop links for a skull cap.
    results = {
        "visual_matches": [
            {"title": "You never know who's going to be in your city", "link": "https://www.facebook.com/p/1"},
            {"title": "Beanie video", "link": "https://m.tiktok.com/@a/video/2"},
            {"title": "Black Skull Cap", "link": "https://shop.example/cap", "price": {"value": "$15"}},
        ]
    }

    matches = parse_matches(results, "black fitted skull cap", limit=3)

    assert [m.link for m in matches] == ["https://shop.example/cap"]


def test_parse_matches_ranks_resale_after_stores() -> None:
    results = {
        "visual_matches": [
            {"title": "Navy Jogger Size XL", "link": "https://www.ebay.co.uk/itm/1", "price": {"value": "$20"}},
            {"title": "Navy Jogger", "link": "https://www.depop.com/products/2", "price": {"value": "$15"}},
            {"title": "Navy Jogger", "link": "https://store.example/jogger", "price": {"value": "$60"}},
            {"title": "Navy Jogger lookbook", "link": "https://blog.example/joggers"},
        ]
    }

    matches = parse_matches(results, "navy athletic jogger", limit=4)

    assert [m.link for m in matches] == [
        "https://store.example/jogger",
        "https://www.ebay.co.uk/itm/1",
        "https://www.depop.com/products/2",
        "https://blog.example/joggers",
    ]


def test_parse_matches_handles_missing_results() -> None:
    assert parse_matches({}, "tank", limit=3) == []
    assert parse_matches({"visual_matches": None}, "tank", limit=3) == []


def test_serpapi_finder_uploads_the_crop_then_searches_google_lens() -> None:
    calls = {}

    def upload_image(image, **kwargs):
        calls["uploaded"] = image.read()
        return {"image_id": "img-123"}

    def search(params, **kwargs):
        calls["params"] = params
        return {"visual_matches": [{"title": "Tank", "link": "https://shop.example/tank"}]}

    finder = SerpApiLensFinder(SimpleNamespace(upload_image=upload_image, search=search))

    matches = finder.find(b"jpeg-bytes", "ribbed tank top")

    assert calls["uploaded"] == b"jpeg-bytes"
    assert calls["params"]["engine"] == "google_lens"
    assert calls["params"]["image_id"] == "img-123"
    assert calls["params"]["type"] == "visual_matches"
    assert calls["params"]["q"] == "ribbed tank top"
    assert [m.link for m in matches] == ["https://shop.example/tank"]


def test_serpapi_errors_mean_no_matches() -> None:
    def upload_image(image, **kwargs):
        raise RuntimeError("SerpApi is down")

    finder = SerpApiLensFinder(SimpleNamespace(upload_image=upload_image, search=None))

    assert finder.find(b"jpeg-bytes", "tank") == []


def test_matching_is_off_without_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SERPAPI_API_KEY", None)

    assert isinstance(get_product_finder(), NoProductFinder)


def test_crop_jpeg_crops_to_the_padded_box() -> None:
    source = make_image_bytes(size=(1000, 2000))

    crop = Image.open(io.BytesIO(crop_jpeg(source, [100, 200, 600, 700], padding=0)))

    # 50% of the width and 25% of the height, scaled down to fit 800px.
    assert crop.size == (400, 800)


def test_parse_matches_ranks_the_garment_type_above_shared_details() -> None:
    # Real case: trousers that repeat "cargo", "drawstring" and "blue" beat actual shorts.
    results = {
        "visual_matches": [
            {"title": "Mens Corduroy Pants Wide Leg Cargo Sweatpants Drawstring Sky Blue",
             "link": "https://a.example/pants", "price": {"value": "$23"}},
            {"title": "Men's Sweat Shorts Elastic Waist Drawstring", "link": "https://b.example/shorts",
             "price": {"value": "$12"}},
        ]
    }

    matches = parse_matches(results, "light blue drawstring cargo shorts", limit=1)

    assert matches[0].link == "https://b.example/shorts"


def test_parse_matches_ranks_kids_items_lower() -> None:
    results = {
        "visual_matches": [
            {"title": "Baby Blue T-Shirt + Short Set", "link": "https://kids.example/set", "price": {"value": "$50"}},
            {"title": "Men's Cargo Shorts Drawstring", "link": "https://shop.example/shorts", "price": {"value": "$15"}},
        ]
    }

    matches = parse_matches(results, "light blue cotton drawstring sweat shorts", limit=2)

    assert [m.link for m in matches] == ["https://shop.example/shorts", "https://kids.example/set"]


def test_serpapi_finder_retries_once() -> None:
    attempts = []

    def upload_image(image, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise TimeoutError("first request timed out")
        return {"image_id": "img-123"}

    def search(params, **kwargs):
        return {"visual_matches": [{"title": "Tank", "link": "https://shop.example/tank"}]}

    finder = SerpApiLensFinder(SimpleNamespace(upload_image=upload_image, search=search))

    assert [m.link for m in finder.find(b"jpeg-bytes", "tank")] == ["https://shop.example/tank"]
    assert len(attempts) == 2


def test_serpapi_error_response_means_no_matches() -> None:
    finder = SerpApiLensFinder(
        SimpleNamespace(
            upload_image=lambda image, **kwargs: {"image_id": "img-123"},
            search=lambda params, **kwargs: {"error": "Your account has run out of searches."},
        )
    )

    assert finder.find(b"jpeg-bytes", "tank") == []
