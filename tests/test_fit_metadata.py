"""Occasion/style tags and the detailed piece fields on fits."""

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import AuthedUser

FITS_URL = "/api/v1/fits"


def post_fit(client: TestClient, user: AuthedUser, image_id: str, **fields):
    return client.post(FITS_URL, headers=user.headers, json={"image_ids": [image_id], **fields})


def test_tags_are_normalized_and_deduplicated(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    user = create_user()

    response = post_fit(
        client,
        user,
        upload_image(user),
        occasion_tags=["  Date   Night ", "date night", "Brunch"],
        style_tags=["Streetwear"],
    )

    assert response.status_code == 201, response.text
    assert response.json()["occasion_tags"] == ["date night", "brunch"]
    assert response.json()["style_tags"] == ["streetwear"]


def test_fits_default_to_no_tags(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    user = create_user()

    body = post_fit(client, user, upload_image(user)).json()

    assert body["occasion_tags"] == []
    assert body["style_tags"] == []


def test_tag_limits(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    user = create_user()
    image_id = upload_image(user)

    assert post_fit(client, user, image_id, style_tags=[f"s{i}" for i in range(11)]).status_code == 422
    assert post_fit(client, user, image_id, style_tags=["x" * 31]).status_code == 422
    assert post_fit(client, user, image_id, style_tags=["   "]).status_code == 422


def test_patch_replaces_only_the_sent_tags(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    user = create_user()
    fit = post_fit(
        client, user, upload_image(user), occasion_tags=["office"], style_tags=["minimalist", "preppy"]
    ).json()

    # Re-sending an existing tag must not clash with the row it replaces.
    response = client.patch(
        f"{FITS_URL}/{fit['id']}", headers=user.headers, json={"style_tags": ["preppy", "classic"]}
    )

    assert response.status_code == 200, response.text
    assert response.json()["style_tags"] == ["preppy", "classic"]
    assert response.json()["occasion_tags"] == ["office"]


def test_patch_null_tags_is_rejected(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    user = create_user()
    fit = post_fit(client, user, upload_image(user)).json()

    response = client.patch(f"{FITS_URL}/{fit['id']}", headers=user.headers, json={"style_tags": None})

    assert response.status_code == 422


def test_tags_appear_in_the_feed(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    user = create_user()
    post_fit(client, user, upload_image(user), style_tags=["streetwear"])

    page = client.get(FITS_URL, headers=user.headers).json()

    assert page["items"][0]["style_tags"] == ["streetwear"]


def test_item_details_round_trip_and_default_to_user_source(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    user = create_user()

    item = post_fit(
        client,
        user,
        upload_image(user),
        items=[
            {
                "category": "outerwear",
                "name": "Corduroy overshirt",
                "color": "mustard",
                "pattern": "solid",
                "material": "corduroy",
                "silhouette": "oversized",
            }
        ],
    ).json()["items"][0]

    assert item["pattern"] == "solid"
    assert item["material"] == "corduroy"
    assert item["silhouette"] == "oversized"
    assert item["source"] == "user"


def test_unknown_item_source_is_rejected(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    user = create_user()

    response = post_fit(
        client, user, upload_image(user), items=[{"category": "top", "name": "Tee", "source": "magic"}]
    )

    assert response.status_code == 422
