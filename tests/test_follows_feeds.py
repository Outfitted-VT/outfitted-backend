from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import user as user_repository
from tests.conftest import AuthedUser

FITS_URL = "/api/v1/fits"
FOLLOWING_FEED_URL = "/api/v1/fits/following"


def user_url(username: str, suffix: str = "") -> str:
    return f"/api/v1/users/{username}{suffix}"


@pytest.fixture
def jane(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("jane")


@pytest.fixture
def bob(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("bob")


@pytest.fixture
def carol(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("carol")


@pytest.fixture
def post_fit(client: TestClient, upload_image: Callable[[AuthedUser], str]) -> Callable[[AuthedUser], str]:
    def _post_fit(user: AuthedUser) -> str:
        response = client.post(FITS_URL, headers=user.headers, json={"image_ids": [upload_image(user)]})
        assert response.status_code == 201
        return response.json()["id"]

    return _post_fit


def follow(client: TestClient, follower: AuthedUser, username: str):
    return client.put(user_url(username, "/follow"), headers=follower.headers)


def profile(client: TestClient, viewer: AuthedUser, username: str) -> dict:
    return client.get(user_url(username), headers=viewer.headers).json()


def usernames(page: dict) -> list[str]:
    return [user["username"] for user in page["items"]]


# --- follow / unfollow ---------------------------------------------------------------------


def test_follow_updates_profile_counts(client: TestClient, jane: AuthedUser, bob: AuthedUser) -> None:
    assert follow(client, jane, "bob").status_code == 204

    bob_profile = profile(client, jane, "bob")
    assert bob_profile["follower_count"] == 1
    assert bob_profile["is_following"] is True
    jane_profile = profile(client, bob, "jane")
    assert jane_profile["following_count"] == 1
    assert jane_profile["is_following"] is False


def test_follow_is_idempotent(client: TestClient, jane: AuthedUser, bob: AuthedUser) -> None:
    follow(client, jane, "bob")
    follow(client, jane, "bob")

    assert profile(client, jane, "bob")["follower_count"] == 1


def test_unfollow(client: TestClient, jane: AuthedUser, bob: AuthedUser) -> None:
    follow(client, jane, "bob")

    assert client.delete(user_url("bob", "/follow"), headers=jane.headers).status_code == 204
    assert profile(client, jane, "bob")["follower_count"] == 0
    assert profile(client, jane, "bob")["is_following"] is False


def test_unfollow_when_not_following_is_fine(client: TestClient, jane: AuthedUser, bob: AuthedUser) -> None:
    assert client.delete(user_url("bob", "/follow"), headers=jane.headers).status_code == 204


def test_cannot_follow_yourself(client: TestClient, jane: AuthedUser) -> None:
    response = follow(client, jane, "jane")

    assert response.status_code == 400
    assert response.json() == {"detail": "You can't follow yourself"}


def test_follow_unknown_user(client: TestClient, jane: AuthedUser) -> None:
    assert follow(client, jane, "nobody").status_code == 404


def test_follow_is_case_insensitive(client: TestClient, jane: AuthedUser, bob: AuthedUser) -> None:
    follow(client, jane, "BOB")

    assert profile(client, jane, "bob")["is_following"] is True


def test_profile_fit_count(client: TestClient, jane: AuthedUser, post_fit) -> None:
    post_fit(jane)
    post_fit(jane)

    assert profile(client, jane, "jane")["fit_count"] == 2


def test_counts_ignore_deactivated_users(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, carol: AuthedUser, db: Session
) -> None:
    follow(client, bob, "jane")
    follow(client, carol, "jane")
    user_repository.get_by_username(db, "carol").is_active = False
    db.commit()

    assert profile(client, jane, "jane")["follower_count"] == 1
    assert usernames(client.get(user_url("jane", "/followers"), headers=jane.headers).json()) == ["bob"]


# --- follower / following lists ------------------------------------------------------------


def test_followers_and_following_lists(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, carol: AuthedUser
) -> None:
    follow(client, bob, "jane")
    follow(client, carol, "jane")
    follow(client, jane, "carol")

    followers = client.get(user_url("jane", "/followers"), headers=jane.headers).json()
    following = client.get(user_url("jane", "/following"), headers=jane.headers).json()

    assert usernames(followers) == ["carol", "bob"]  # most recent first
    assert usernames(following) == ["carol"]
    assert set(followers["items"][0]) == {"id", "username", "full_name", "avatar"}


def test_follower_list_paginates(
    client: TestClient, jane: AuthedUser, create_user: Callable[..., AuthedUser]
) -> None:
    names = [f"fan{i}" for i in range(5)]
    for name in names:
        follow(client, create_user(name), "jane")

    seen, cursor = [], None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = client.get(user_url("jane", "/followers"), headers=jane.headers, params=params).json()
        seen += usernames(page)
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == list(reversed(names))


def test_follower_list_unknown_user(client: TestClient, jane: AuthedUser) -> None:
    assert client.get(user_url("nobody", "/followers"), headers=jane.headers).status_code == 404


# --- feeds ---------------------------------------------------------------------------------


def test_following_feed_shows_followed_and_own_fits(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, carol: AuthedUser, post_fit
) -> None:
    follow(client, jane, "bob")
    own = post_fit(jane)
    followed = post_fit(bob)
    post_fit(carol)  # not followed

    feed = client.get(FOLLOWING_FEED_URL, headers=jane.headers).json()

    assert [fit["id"] for fit in feed["items"]] == [followed, own]


def test_following_feed_after_unfollow(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    follow(client, jane, "bob")
    post_fit(bob)
    client.delete(user_url("bob", "/follow"), headers=jane.headers)

    assert client.get(FOLLOWING_FEED_URL, headers=jane.headers).json()["items"] == []


def test_explore_feed_shows_everyone_newest_first(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, carol: AuthedUser, post_fit
) -> None:
    posted = [post_fit(jane), post_fit(bob), post_fit(carol)]

    feed = client.get(FITS_URL, headers=jane.headers).json()

    assert [fit["id"] for fit in feed["items"]] == list(reversed(posted))


def test_explore_feed_paginates(client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit) -> None:
    posted = [post_fit(user) for user in (jane, bob, jane, bob, jane)]

    seen, cursor = [], None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = client.get(FITS_URL, headers=jane.headers, params=params).json()
        seen += [fit["id"] for fit in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == list(reversed(posted))


def test_feeds_include_viewer_state(client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit) -> None:
    follow(client, jane, "bob")
    fit_id = post_fit(bob)
    client.put(f"{FITS_URL}/{fit_id}/like", headers=jane.headers)

    fit = client.get(FOLLOWING_FEED_URL, headers=jane.headers).json()["items"][0]

    assert (fit["like_count"], fit["liked_by_me"]) == (1, True)


def test_feeds_hide_deactivated_authors(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit, db: Session
) -> None:
    follow(client, jane, "bob")
    post_fit(bob)
    user_repository.get_by_username(db, "bob").is_active = False
    db.commit()

    assert client.get(FITS_URL, headers=jane.headers).json()["items"] == []
    assert client.get(FOLLOWING_FEED_URL, headers=jane.headers).json()["items"] == []


def test_feed_route_is_not_parsed_as_fit_id(client: TestClient, jane: AuthedUser) -> None:
    assert client.get(FOLLOWING_FEED_URL, headers=jane.headers).status_code == 200


def test_feeds_require_login(client: TestClient) -> None:
    assert client.get(FITS_URL).status_code == 401
    assert client.get(FOLLOWING_FEED_URL).status_code == 401
