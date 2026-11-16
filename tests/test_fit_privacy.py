"""Who can see a fit, by privacy tier: Public for everyone, Friends ("close_friends") only for
people who follow each other with the poster, Vault for the poster only."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AuthedUser

FITS_URL = "/api/v1/fits"
USERS_URL = "/api/v1/users"


@pytest.fixture
def people(client: TestClient, create_user: Callable[..., AuthedUser]) -> dict[str, AuthedUser]:
    """Maya posts. Leo and Maya follow each other; Ivy follows Maya, Maya doesn't follow back;
    Sam follows no one."""
    users = {name: create_user(name) for name in ("maya", "leo", "ivy", "sam")}
    for follower, followee in (("leo", "maya"), ("maya", "leo"), ("ivy", "maya")):
        response = client.put(f"{USERS_URL}/{followee}/follow", headers=users[follower].headers)
        assert response.status_code == 204, response.text
    return users


@pytest.fixture
def posts(client: TestClient, people, upload_image) -> dict[str, str]:
    """One fit by Maya per tier: tier -> fit id."""
    maya = people["maya"]
    ids = {}
    for tier in ("public", "close_friends", "vault"):
        response = client.post(
            FITS_URL, headers=maya.headers, json={"image_ids": [upload_image(maya)], "privacy_tier": tier}
        )
        assert response.status_code == 201, response.text
        ids[tier] = response.json()["id"]
    return ids


# Which of Maya's fits each person may see.
CAN_SEE = {
    "maya": {"public", "close_friends", "vault"},
    "leo": {"public", "close_friends"},  # mutual follow
    "ivy": {"public"},  # follows Maya, not followed back
    "sam": {"public"},  # stranger
}


def tiers(posts: dict[str, str], fit_ids) -> set[str]:
    by_id = {fit_id: tier for tier, fit_id in posts.items()}
    return {by_id[i] for i in fit_ids if i in by_id}


@pytest.mark.parametrize("viewer", CAN_SEE)
def test_profile_shows_only_what_the_viewer_may_see(client: TestClient, people, posts, viewer) -> None:
    response = client.get(f"{USERS_URL}/maya/fits", headers=people[viewer].headers)
    assert response.status_code == 200, response.text
    assert tiers(posts, [f["id"] for f in response.json()["items"]]) == CAN_SEE[viewer]


@pytest.mark.parametrize("viewer", ["maya", "leo", "ivy"])
def test_circle_feed_shows_friends_posts_to_mutual_follows_only(client: TestClient, people, posts, viewer) -> None:
    response = client.get(f"{FITS_URL}/following", headers=people[viewer].headers)
    assert response.status_code == 200, response.text
    assert tiers(posts, [f["id"] for f in response.json()["items"]]) == CAN_SEE[viewer]


def test_explore_feed_is_public_only(client: TestClient, people, posts) -> None:
    for viewer in people.values():
        response = client.get(FITS_URL, headers=viewer.headers)
        assert tiers(posts, [f["id"] for f in response.json()["items"]]) == {"public"}


@pytest.mark.parametrize("viewer", CAN_SEE)
def test_direct_link_and_actions_follow_the_same_rule(client: TestClient, people, posts, viewer) -> None:
    headers = people[viewer].headers
    for tier, fit_id in posts.items():
        expected = 200 if tier in CAN_SEE[viewer] else 404
        assert client.get(f"{FITS_URL}/{fit_id}", headers=headers).status_code == expected, (viewer, tier)
        assert client.get(f"{FITS_URL}/{fit_id}/comments", headers=headers).status_code == expected
        like = client.put(f"{FITS_URL}/{fit_id}/like", headers=headers).status_code
        assert (like == 404) == (expected == 404), (viewer, tier, like)


def test_saved_friends_post_disappears_when_no_longer_mutual(client: TestClient, people, posts) -> None:
    leo = people["leo"]
    fit_id = posts["close_friends"]
    assert client.put(f"{FITS_URL}/{fit_id}/save", headers=leo.headers).status_code == 204
    saved = client.get(f"{USERS_URL}/me/saved", headers=leo.headers).json()["items"]
    assert [f["id"] for f in saved] == [fit_id]

    # Maya stops following Leo back: the Friends post is no longer his to see.
    assert client.delete(f"{USERS_URL}/leo/follow", headers=people["maya"].headers).status_code == 204
    assert client.get(f"{USERS_URL}/me/saved", headers=leo.headers).json()["items"] == []
    assert client.get(f"{FITS_URL}/{fit_id}", headers=leo.headers).status_code == 404


@pytest.mark.parametrize("viewer", sorted(CAN_SEE))
def test_profile_fit_count_counts_only_visible_fits(client: TestClient, people, posts, viewer: str) -> None:
    response = client.get(f"{USERS_URL}/maya", headers=people[viewer].headers)

    assert response.status_code == 200, response.text
    assert response.json()["fit_count"] == len(CAN_SEE[viewer])
