"""Saving a single piece (a shoe, a sweater) from a fit instead of the whole fit."""

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import AuthedUser

FITS_URL = "/api/v1/fits"
PIECES_URL = "/api/v1/users/me/saved-pieces"


def post_fit(client: TestClient, user: AuthedUser, upload_image, **extra) -> dict:
    photo = upload_image(user)
    body = {
        "image_ids": [photo],
        "items": [
            {"category": "outerwear", "name": "Blue jacket", "brand": "Zara", "color": "blue",
             "url": "https://example.com/jacket", "pin": {"image_id": photo, "x": 0.4, "y": 0.3}},
            {"category": "shoes", "name": "Sambas", "pin": {"image_id": photo, "x": 0.5, "y": 0.9}},
        ],
        **extra,
    }
    response = client.post(FITS_URL, headers=user.headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def save(client: TestClient, user: AuthedUser, fit: dict, index: int):
    return client.post(f"{FITS_URL}/{fit['id']}/items/{fit['items'][index]['id']}/save", headers=user.headers)


def test_save_a_piece_and_list_it(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image
) -> None:
    jane, bob = create_user("jane"), create_user("bob")
    fit = post_fit(client, jane, upload_image)

    response = save(client, bob, fit, 0)

    assert response.status_code == 201, response.text
    piece = response.json()
    assert piece["name"] == "Blue jacket"
    assert piece["brand"] == "Zara"
    assert piece["url"] == "https://example.com/jacket"
    assert piece["fit_id"] == fit["id"]
    assert piece["source_username"] == "jane"
    assert piece["photo"]["id"] == fit["images"][0]["id"]
    # Two pieces share the photo, so the piece is shown zoomed on its pin.
    assert piece["zoom"] is True
    assert piece["pin"] == {"x": 0.4, "y": 0.3}

    listed = client.get(PIECES_URL, headers=bob.headers).json()
    assert [p["id"] for p in listed["items"]] == [piece["id"]]
    # Only the saver sees their saved pieces.
    assert client.get(PIECES_URL, headers=jane.headers).json()["items"] == []


def test_fit_items_say_which_pieces_you_saved(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image
) -> None:
    jane, bob = create_user("jane"), create_user("bob")
    fit = post_fit(client, jane, upload_image)
    piece = save(client, bob, fit, 1).json()

    as_bob = client.get(f"{FITS_URL}/{fit['id']}", headers=bob.headers).json()
    as_jane = client.get(f"{FITS_URL}/{fit['id']}", headers=jane.headers).json()

    assert [item["saved_piece_id"] for item in as_bob["items"]] == [None, piece["id"]]
    assert [item["saved_piece_id"] for item in as_jane["items"]] == [None, None]


def test_saving_twice_returns_the_same_piece(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image
) -> None:
    jane, bob = create_user("jane"), create_user("bob")
    fit = post_fit(client, jane, upload_image)

    first = save(client, bob, fit, 0).json()
    second = save(client, bob, fit, 0).json()

    assert first["id"] == second["id"]
    assert len(client.get(PIECES_URL, headers=bob.headers).json()["items"]) == 1


def test_saved_piece_survives_the_fit_being_edited_and_deleted(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image
) -> None:
    jane, bob = create_user("jane"), create_user("bob")
    fit = post_fit(client, jane, upload_image)
    piece = save(client, bob, fit, 1).json()

    # Editing the pieces rebuilds them with new ids; the save still matches by name.
    items = [
        {"category": item["category"], "name": item["name"], "url": "https://example.com/shop"}
        for item in fit["items"]
    ]
    edited = client.patch(f"{FITS_URL}/{fit['id']}", headers=jane.headers, json={"items": items})
    assert edited.status_code == 200, edited.text
    as_bob = client.get(f"{FITS_URL}/{fit['id']}", headers=bob.headers).json()
    assert as_bob["items"][1]["saved_piece_id"] == piece["id"]

    client.delete(f"{FITS_URL}/{fit['id']}", headers=jane.headers)
    [kept] = client.get(PIECES_URL, headers=bob.headers).json()["items"]
    # The save is a copy, so it stays. (Postgres also clears fit_id; the SQLite test database
    # doesn't enforce foreign keys.)
    assert kept["id"] == piece["id"]
    assert kept["name"] == "Sambas"


def test_unsave_a_piece(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image
) -> None:
    jane, bob = create_user("jane"), create_user("bob")
    fit = post_fit(client, jane, upload_image)
    piece = save(client, bob, fit, 0).json()

    # Someone else can't remove it.
    assert client.delete(f"{PIECES_URL}/{piece['id']}", headers=jane.headers).status_code == 404
    assert client.delete(f"{PIECES_URL}/{piece['id']}", headers=bob.headers).status_code == 204
    assert client.get(PIECES_URL, headers=bob.headers).json()["items"] == []


def test_cant_save_a_piece_from_a_fit_you_cant_see(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image
) -> None:
    jane, bob = create_user("jane"), create_user("bob")
    fit = post_fit(client, jane, upload_image, privacy_tier="vault")

    assert save(client, bob, fit, 0).status_code == 404
    missing = client.post(
        f"{FITS_URL}/{fit['id']}/items/00000000-0000-0000-0000-000000000000/save", headers=jane.headers
    )
    assert missing.status_code == 404


def test_a_piece_with_its_own_photo_is_saved_with_that_photo(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image
) -> None:
    jane, bob = create_user("jane"), create_user("bob")
    cover, sneaker = upload_image(jane), upload_image(jane)
    body = {
        "image_ids": [cover, sneaker],
        "items": [{"category": "shoes", "name": "Sambas", "image_id": sneaker}],
    }
    fit = client.post(FITS_URL, headers=jane.headers, json=body).json()
    assert fit["items"][0]["image"]["id"] == sneaker

    piece = save(client, bob, fit, 0).json()

    assert piece["photo"]["id"] == sneaker
    assert piece["zoom"] is False
    assert piece["pin"] is None


def test_an_item_photo_must_belong_to_the_fit_or_its_try_on(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image
) -> None:
    jane = create_user("jane")
    stray = upload_image(jane)
    body = {
        "image_ids": [upload_image(jane)],
        "items": [{"category": "shoes", "name": "Sambas", "image_id": stray}],
    }

    response = client.post(FITS_URL, headers=jane.headers, json=body)

    assert response.status_code == 400
    assert "item image" in response.json()["detail"]
