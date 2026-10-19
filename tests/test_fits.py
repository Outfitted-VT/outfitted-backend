from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.image import Image
from app.repositories import user as user_repository
from app.storage import LocalStorage
from tests.conftest import AuthedUser

FITS_URL = "/api/v1/fits"


def fit_url(fit_id: str) -> str:
    return f"{FITS_URL}/{fit_id}"


def user_fits_url(username: str) -> str:
    return f"/api/v1/users/{username}/fits"


@pytest.fixture
def jane(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("jane")


@pytest.fixture
def post_fit(client: TestClient, upload_image: Callable[[AuthedUser], str]) -> Callable[..., dict]:
    """Post a fit with freshly uploaded images and return the response body."""

    def _post_fit(user: AuthedUser, images: int = 1, **fields) -> dict:
        image_ids = [upload_image(user) for _ in range(images)]
        response = client.post(FITS_URL, headers=user.headers, json={"image_ids": image_ids, **fields})
        assert response.status_code == 201, response.text
        return response.json()

    return _post_fit


def stored_file(storage: LocalStorage, url: str) -> Path:
    return storage.root / url.removeprefix(settings.MEDIA_BASE_URL.rstrip("/") + "/")


# --- creating ------------------------------------------------------------------------------


def test_post_fit_with_items_and_pin(
    client: TestClient, jane: AuthedUser, upload_image: Callable[[AuthedUser], str]
) -> None:
    first, second = upload_image(jane), upload_image(jane)

    response = client.post(
        FITS_URL,
        headers=jane.headers,
        json={
            "image_ids": [second, first],
            "caption": "  Sunday fit  ",
            "items": [
                {
                    "category": "outerwear",
                    "name": "Denim jacket",
                    "brand": "Levi's",
                    "color": "blue",
                    "url": "https://example.com/jacket",
                    "pin": {"image_id": first, "x": 0.4, "y": 0.3},
                },
                {"category": "shoes", "name": "Sambas"},
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["caption"] == "Sunday fit"
    assert body["author"]["username"] == "jane"
    assert [image["id"] for image in body["images"]] == [second, first]
    assert [item["name"] for item in body["items"]] == ["Denim jacket", "Sambas"]
    assert body["items"][0]["pin"] == {"image_id": first, "x": 0.4, "y": 0.3}
    assert body["items"][0]["url"] == "https://example.com/jacket"
    assert body["items"][1]["pin"] is None
    assert body["items"][1]["brand"] is None


def test_get_fit(client: TestClient, jane: AuthedUser, post_fit: Callable[..., dict]) -> None:
    fit = post_fit(jane, caption="hello")

    response = client.get(fit_url(fit["id"]), headers=jane.headers)

    assert response.status_code == 200
    assert response.json() == fit


@pytest.mark.parametrize(
    "fields",
    [
        {"image_ids": []},
        {"items": [{"category": "hat", "name": "Cap"}]},
        {"items": [{"category": "top", "name": "   "}]},
        {"items": [{"category": "top", "name": "Tee", "url": "not a url"}]},
        {"items": [{"category": "top", "name": "Tee", "pin": {"image_id": "IMAGE", "x": 1.5, "y": 0}}]},
        {"caption": "x" * 2201},
    ],
    ids=["no-images", "bad-category", "blank-name", "bad-url", "pin-out-of-range", "long-caption"],
)
def test_post_fit_validation(
    client: TestClient, jane: AuthedUser, upload_image: Callable[[AuthedUser], str], fields: dict
) -> None:
    image_id = upload_image(jane)
    body = {"image_ids": [image_id], **fields}
    for item in body.get("items", []):
        if "pin" in item:
            item["pin"]["image_id"] = image_id

    assert client.post(FITS_URL, headers=jane.headers, json=body).status_code == 422


def test_post_fit_too_many_images(
    client: TestClient, jane: AuthedUser, upload_image: Callable[[AuthedUser], str]
) -> None:
    image_ids = [upload_image(jane) for _ in range(11)]

    assert client.post(FITS_URL, headers=jane.headers, json={"image_ids": image_ids}).status_code == 422


def test_post_fit_duplicate_image(
    client: TestClient, jane: AuthedUser, upload_image: Callable[[AuthedUser], str]
) -> None:
    image_id = upload_image(jane)

    response = client.post(FITS_URL, headers=jane.headers, json={"image_ids": [image_id, image_id]})

    assert response.status_code == 422


def test_pin_must_reference_fit_image(
    client: TestClient, jane: AuthedUser, upload_image: Callable[[AuthedUser], str]
) -> None:
    in_fit, not_in_fit = upload_image(jane), upload_image(jane)

    response = client.post(
        FITS_URL,
        headers=jane.headers,
        json={
            "image_ids": [in_fit],
            "items": [{"category": "top", "name": "Tee", "pin": {"image_id": not_in_fit, "x": 0, "y": 0}}],
        },
    )

    assert response.status_code == 422


def test_cannot_post_someone_elses_image(
    client: TestClient,
    jane: AuthedUser,
    create_user: Callable[..., AuthedUser],
    upload_image: Callable[[AuthedUser], str],
) -> None:
    bob_image = upload_image(create_user("bob"))

    response = client.post(FITS_URL, headers=jane.headers, json={"image_ids": [bob_image]})

    assert response.status_code == 400
    assert response.json() == {"detail": "Image not found"}


def test_image_can_only_be_in_one_fit(
    client: TestClient, jane: AuthedUser, upload_image: Callable[[AuthedUser], str]
) -> None:
    image_id = upload_image(jane)
    client.post(FITS_URL, headers=jane.headers, json={"image_ids": [image_id]})

    response = client.post(FITS_URL, headers=jane.headers, json={"image_ids": [image_id]})

    assert response.status_code == 409


def test_get_unknown_fit(client: TestClient, jane: AuthedUser) -> None:
    response = client.get(fit_url("00000000-0000-0000-0000-000000000000"), headers=jane.headers)

    assert response.status_code == 404


def test_fits_require_login(client: TestClient, jane: AuthedUser, post_fit: Callable[..., dict]) -> None:
    fit = post_fit(jane)

    assert client.get(fit_url(fit["id"])).status_code == 401
    assert client.post(FITS_URL, json={"image_ids": []}).status_code == 401


# --- editing -------------------------------------------------------------------------------


def test_edit_caption_keeps_items(
    client: TestClient, jane: AuthedUser, post_fit: Callable[..., dict]
) -> None:
    fit = post_fit(jane, caption="old", items=[{"category": "top", "name": "Tee"}])

    response = client.patch(fit_url(fit["id"]), headers=jane.headers, json={"caption": "new"})

    assert response.status_code == 200
    assert response.json()["caption"] == "new"
    assert [item["name"] for item in response.json()["items"]] == ["Tee"]


def test_edit_replaces_items(client: TestClient, jane: AuthedUser, post_fit: Callable[..., dict]) -> None:
    fit = post_fit(jane, items=[{"category": "top", "name": "Tee"}])
    image_id = fit["images"][0]["id"]

    response = client.patch(
        fit_url(fit["id"]),
        headers=jane.headers,
        json={"items": [{"category": "shoes", "name": "Boots", "pin": {"image_id": image_id, "x": 0.5, "y": 0.9}}]},
    )

    assert [item["name"] for item in response.json()["items"]] == ["Boots"]
    assert client.get(fit_url(fit["id"]), headers=jane.headers).json()["items"][0]["name"] == "Boots"


def test_edit_pin_must_reference_fit_image(
    client: TestClient, jane: AuthedUser, post_fit: Callable[..., dict], upload_image: Callable[[AuthedUser], str]
) -> None:
    fit = post_fit(jane)
    other_image = upload_image(jane)

    response = client.patch(
        fit_url(fit["id"]),
        headers=jane.headers,
        json={"items": [{"category": "top", "name": "Tee", "pin": {"image_id": other_image, "x": 0, "y": 0}}]},
    )

    assert response.status_code == 400


def test_cannot_edit_someone_elses_fit(
    client: TestClient, jane: AuthedUser, create_user: Callable[..., AuthedUser], post_fit: Callable[..., dict]
) -> None:
    fit = post_fit(jane)
    bob = create_user("bob")

    response = client.patch(fit_url(fit["id"]), headers=bob.headers, json={"caption": "mine now"})

    assert response.status_code == 403


# --- deleting ------------------------------------------------------------------------------


def test_delete_fit_removes_photos(
    client: TestClient, jane: AuthedUser, post_fit: Callable[..., dict], storage: LocalStorage, db: Session
) -> None:
    fit = post_fit(jane, images=2)
    files = [stored_file(storage, image["url"]) for image in fit["images"]]
    assert all(path.exists() for path in files)

    response = client.delete(fit_url(fit["id"]), headers=jane.headers)

    assert response.status_code == 204
    assert client.get(fit_url(fit["id"]), headers=jane.headers).status_code == 404
    assert not any(path.exists() for path in files)
    assert db.query(Image).count() == 0


def test_delete_fit_keeps_photo_used_as_avatar(
    client: TestClient, jane: AuthedUser, post_fit: Callable[..., dict], storage: LocalStorage
) -> None:
    fit = post_fit(jane)
    image = fit["images"][0]
    client.patch("/api/v1/users/me", headers=jane.headers, json={"avatar_image_id": image["id"]})

    client.delete(fit_url(fit["id"]), headers=jane.headers)

    assert stored_file(storage, image["url"]).exists()
    me = client.get("/api/v1/users/me", headers=jane.headers).json()
    assert me["avatar"]["id"] == image["id"]


def test_cannot_delete_someone_elses_fit(
    client: TestClient, jane: AuthedUser, create_user: Callable[..., AuthedUser], post_fit: Callable[..., dict]
) -> None:
    fit = post_fit(jane)
    bob = create_user("bob")

    assert client.delete(fit_url(fit["id"]), headers=bob.headers).status_code == 403
    assert client.get(fit_url(fit["id"]), headers=jane.headers).status_code == 200


# --- listing a user's fits -----------------------------------------------------------------


def test_list_user_fits_paginates_newest_first(
    client: TestClient, jane: AuthedUser, create_user: Callable[..., AuthedUser], post_fit: Callable[..., dict]
) -> None:
    posted = [post_fit(jane, caption=f"fit {i}")["id"] for i in range(5)]
    post_fit(create_user("bob"))  # someone else's fit shouldn't appear

    seen, cursor = [], None
    for _ in range(3):
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = client.get(user_fits_url("jane"), headers=jane.headers, params=params).json()
        seen += [fit["id"] for fit in page["items"]]
        cursor = page["next_cursor"]

    assert seen == list(reversed(posted))
    assert cursor is None


def test_new_fits_during_scrolling_dont_cause_duplicates(
    client: TestClient, jane: AuthedUser, post_fit: Callable[..., dict]
) -> None:
    for _ in range(3):
        post_fit(jane)
    first_page = client.get(user_fits_url("jane"), headers=jane.headers, params={"limit": 2}).json()

    post_fit(jane)  # posted while the user is scrolling
    second_page = client.get(
        user_fits_url("jane"), headers=jane.headers, params={"limit": 2, "cursor": first_page["next_cursor"]}
    ).json()

    first_ids = {fit["id"] for fit in first_page["items"]}
    assert len(second_page["items"]) == 1
    assert second_page["items"][0]["id"] not in first_ids


def test_list_fits_of_deactivated_user_is_hidden(
    client: TestClient, jane: AuthedUser, create_user: Callable[..., AuthedUser], post_fit: Callable[..., dict], db: Session
) -> None:
    fit = post_fit(create_user("bob"))
    bob = user_repository.get_by_username(db, "bob")
    bob.is_active = False
    db.commit()

    assert client.get(user_fits_url("bob"), headers=jane.headers).status_code == 404
    assert client.get(fit_url(fit["id"]), headers=jane.headers).status_code == 404


def test_list_fits_invalid_cursor(client: TestClient, jane: AuthedUser) -> None:
    response = client.get(user_fits_url("jane"), headers=jane.headers, params={"cursor": "garbage"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid cursor"}


def test_list_fits_limit_bounds(client: TestClient, jane: AuthedUser) -> None:
    assert client.get(user_fits_url("jane"), headers=jane.headers, params={"limit": 0}).status_code == 422
    assert client.get(user_fits_url("jane"), headers=jane.headers, params={"limit": 51}).status_code == 422
