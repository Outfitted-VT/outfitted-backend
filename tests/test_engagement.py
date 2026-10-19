from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import user as user_repository
from tests.conftest import AuthedUser

FITS_URL = "/api/v1/fits"
SAVED_URL = "/api/v1/users/me/saved"


def fit_url(fit_id: str) -> str:
    return f"{FITS_URL}/{fit_id}"


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


def get_fit(client: TestClient, user: AuthedUser, fit_id: str) -> dict:
    return client.get(fit_url(fit_id), headers=user.headers).json()


# --- likes ---------------------------------------------------------------------------------


def test_new_fit_has_no_likes(client: TestClient, jane: AuthedUser, post_fit) -> None:
    fit = get_fit(client, jane, post_fit(jane))

    assert (fit["like_count"], fit["liked_by_me"], fit["saved_by_me"]) == (0, False, False)


def test_like_and_unlike(client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane)

    assert client.put(f"{fit_url(fit_id)}/like", headers=bob.headers).status_code == 204
    assert get_fit(client, bob, fit_id)["liked_by_me"] is True
    assert get_fit(client, bob, fit_id)["like_count"] == 1
    # liked_by_me is per viewer.
    assert get_fit(client, jane, fit_id)["liked_by_me"] is False

    assert client.delete(f"{fit_url(fit_id)}/like", headers=bob.headers).status_code == 204
    assert get_fit(client, bob, fit_id)["like_count"] == 0
    assert get_fit(client, bob, fit_id)["liked_by_me"] is False


def test_like_is_idempotent(client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane)

    client.put(f"{fit_url(fit_id)}/like", headers=bob.headers)
    client.put(f"{fit_url(fit_id)}/like", headers=bob.headers)

    assert get_fit(client, bob, fit_id)["like_count"] == 1


def test_unlike_without_like_is_fine(client: TestClient, jane: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane)

    assert client.delete(f"{fit_url(fit_id)}/like", headers=jane.headers).status_code == 204


def test_like_counts_multiple_users(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, create_user, post_fit
) -> None:
    fit_id = post_fit(jane)
    carol = create_user("carol")

    for user in (jane, bob, carol):
        client.put(f"{fit_url(fit_id)}/like", headers=user.headers)

    assert get_fit(client, jane, fit_id)["like_count"] == 3


def test_concurrent_double_like_is_ignored(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit, monkeypatch
) -> None:
    from app.repositories import engagement as engagement_repository

    fit_id = post_fit(jane)
    client.put(f"{fit_url(fit_id)}/like", headers=bob.headers)
    # Simulate a second request whose "already liked?" check ran before the first committed.
    monkeypatch.setattr(engagement_repository, "has_liked", lambda db, user_id, fit_id: False)

    response = client.put(f"{fit_url(fit_id)}/like", headers=bob.headers)

    assert response.status_code == 204
    monkeypatch.undo()
    assert get_fit(client, bob, fit_id)["like_count"] == 1


def test_like_unknown_fit(client: TestClient, jane: AuthedUser) -> None:
    unknown = "00000000-0000-0000-0000-000000000000"

    assert client.put(f"{fit_url(unknown)}/like", headers=jane.headers).status_code == 404
    assert client.delete(f"{fit_url(unknown)}/like", headers=jane.headers).status_code == 404


def test_likes_removed_with_fit(client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane)
    client.put(f"{fit_url(fit_id)}/like", headers=bob.headers)
    client.put(f"{fit_url(fit_id)}/save", headers=bob.headers)

    assert client.delete(fit_url(fit_id), headers=jane.headers).status_code == 204
    assert client.get(SAVED_URL, headers=bob.headers).json()["items"] == []


# --- saves ---------------------------------------------------------------------------------


def test_save_and_list_saved_most_recent_first(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    first, second, unsaved = post_fit(jane), post_fit(jane), post_fit(jane)

    client.put(f"{fit_url(second)}/save", headers=bob.headers)
    client.put(f"{fit_url(first)}/save", headers=bob.headers)

    page = client.get(SAVED_URL, headers=bob.headers).json()
    assert [fit["id"] for fit in page["items"]] == [first, second]
    assert all(fit["saved_by_me"] for fit in page["items"])
    assert page["next_cursor"] is None


def test_saves_are_private(client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane)
    client.put(f"{fit_url(fit_id)}/save", headers=bob.headers)

    assert client.get(SAVED_URL, headers=jane.headers).json()["items"] == []
    assert get_fit(client, jane, fit_id)["saved_by_me"] is False


def test_unsave(client: TestClient, jane: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane)
    client.put(f"{fit_url(fit_id)}/save", headers=jane.headers)

    assert client.delete(f"{fit_url(fit_id)}/save", headers=jane.headers).status_code == 204
    assert client.get(SAVED_URL, headers=jane.headers).json()["items"] == []


def test_save_is_idempotent(client: TestClient, jane: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane)

    client.put(f"{fit_url(fit_id)}/save", headers=jane.headers)
    client.put(f"{fit_url(fit_id)}/save", headers=jane.headers)

    assert len(client.get(SAVED_URL, headers=jane.headers).json()["items"]) == 1


def test_saved_list_paginates(client: TestClient, jane: AuthedUser, post_fit) -> None:
    fit_ids = [post_fit(jane) for _ in range(5)]
    for fit_id in fit_ids:
        client.put(f"{fit_url(fit_id)}/save", headers=jane.headers)

    seen, cursor = [], None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = client.get(SAVED_URL, headers=jane.headers, params=params).json()
        seen += [fit["id"] for fit in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == list(reversed(fit_ids))


def test_saved_list_hides_deactivated_authors(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit, db: Session
) -> None:
    fit_id = post_fit(bob)
    client.put(f"{fit_url(fit_id)}/save", headers=jane.headers)
    user_repository.get_by_username(db, "bob").is_active = False
    db.commit()

    assert client.get(SAVED_URL, headers=jane.headers).json()["items"] == []


def test_user_fits_list_includes_viewer_state(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)
    client.put(f"{fit_url(fit_id)}/like", headers=bob.headers)

    fit = client.get("/api/v1/users/jane/fits", headers=bob.headers).json()["items"][0]

    assert (fit["like_count"], fit["liked_by_me"], fit["saved_by_me"]) == (1, True, False)
