from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AuthedUser

FITS_URL = "/api/v1/fits"


@pytest.fixture
def jane(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("jane")


@pytest.fixture
def bob(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("bob")


@pytest.fixture
def post_fit(client: TestClient, upload_image: Callable[[AuthedUser], str]) -> Callable[[AuthedUser], str]:
    def _post_fit(user: AuthedUser) -> str:
        response = client.post(FITS_URL, headers=user.headers, json={"image_ids": [upload_image(user)]})
        assert response.status_code == 201
        return response.json()["id"]

    return _post_fit


def test_post_and_list_comments(client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit: Callable[[AuthedUser], str]):
    fit_id = post_fit(jane)

    # Bob posts a comment
    res = client.post(
        f"{FITS_URL}/{fit_id}/comments",
        headers=bob.headers,
        json={"content": "Love the proportions on this coat!"},
    )
    assert res.status_code == 201
    comment_data = res.json()
    assert comment_data["content"] == "Love the proportions on this coat!"
    assert comment_data["author"]["username"] == "bob"

    # Jane posts a reply
    res2 = client.post(
        f"{FITS_URL}/{fit_id}/comments",
        headers=jane.headers,
        json={"content": "Thank you! Thrifted it last week."},
    )
    assert res2.status_code == 201

    # List comments
    list_res = client.get(f"{FITS_URL}/{fit_id}/comments", headers=bob.headers)
    assert list_res.status_code == 200
    comments = list_res.json()
    assert len(comments) == 2
    assert comments[0]["content"] == "Love the proportions on this coat!"
    assert comments[1]["content"] == "Thank you! Thrifted it last week."

    # Check that FitRead reflects comment_count == 2
    fit_res = client.get(f"{FITS_URL}/{fit_id}", headers=jane.headers)
    assert fit_res.status_code == 200
    assert fit_res.json()["comment_count"] == 2


def test_delete_comment(client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit: Callable[[AuthedUser], str]):
    fit_id = post_fit(jane)

    res = client.post(
        f"{FITS_URL}/{fit_id}/comments",
        headers=bob.headers,
        json={"content": "Nice look!"},
    )
    comment_id = res.json()["id"]

    # Jane cannot delete Bob's comment
    del_res = client.delete(f"{FITS_URL}/{fit_id}/comments/{comment_id}", headers=jane.headers)
    assert del_res.status_code == 404

    # Bob deletes his own comment
    del_res2 = client.delete(f"{FITS_URL}/{fit_id}/comments/{comment_id}", headers=bob.headers)
    assert del_res2.status_code == 204

    # Now comment list is empty
    list_res = client.get(f"{FITS_URL}/{fit_id}/comments", headers=bob.headers)
    assert len(list_res.json()) == 0
