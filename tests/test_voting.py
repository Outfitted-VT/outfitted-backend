from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AuthedUser

FITS_URL = "/api/v1/fits"
UNKNOWN_FIT = "00000000-0000-0000-0000-000000000000"


def fit_url(fit_id: str) -> str:
    return f"{FITS_URL}/{fit_id}"


def vote_url(fit_id: str) -> str:
    return f"{fit_url(fit_id)}/vote"


@pytest.fixture
def jane(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("jane")


@pytest.fixture
def bob(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("bob")


@pytest.fixture
def post_fit(
    client: TestClient, upload_image: Callable[[AuthedUser], str]
) -> Callable[[AuthedUser], str]:
    def _post_fit(user: AuthedUser) -> str:
        response = client.post(
            FITS_URL, headers=user.headers, json={"image_ids": [upload_image(user)]}
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    return _post_fit


def get_fit(client: TestClient, user: AuthedUser, fit_id: str) -> dict:
    return client.get(fit_url(fit_id), headers=user.headers).json()


def cast(client: TestClient, user: AuthedUser, fit_id: str, choice: str):
    return client.put(vote_url(fit_id), headers=user.headers, json={"choice": choice})


# --- casting -------------------------------------------------------------------------------


def test_new_fit_has_no_votes(client: TestClient, jane: AuthedUser, post_fit) -> None:
    fit = get_fit(client, jane, post_fit(jane))

    assert fit["votes"] == {"wear": 0, "rethink": 0}
    assert fit["my_vote"] is None


def test_vote_is_counted_and_returned(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    response = cast(client, bob, fit_id, "wear")

    assert response.status_code == 200, response.text
    # The response carries the new tallies, so the client needn't refetch.
    assert response.json()["votes"] == {"wear": 1, "rethink": 0}
    assert response.json()["my_vote"] == "wear"
    assert get_fit(client, bob, fit_id)["votes"] == {"wear": 1, "rethink": 0}


def test_my_vote_is_per_viewer(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)
    cast(client, bob, fit_id, "rethink")

    assert get_fit(client, bob, fit_id)["my_vote"] == "rethink"
    assert get_fit(client, jane, fit_id)["my_vote"] is None
    # ...but the tallies are the same for everyone.
    assert get_fit(client, jane, fit_id)["votes"] == {"wear": 0, "rethink": 1}


def test_changing_your_vote_replaces_it(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    cast(client, bob, fit_id, "wear")
    response = cast(client, bob, fit_id, "rethink")

    assert response.json()["votes"] == {"wear": 0, "rethink": 1}
    assert response.json()["my_vote"] == "rethink"


def test_voting_twice_the_same_way_is_idempotent(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    cast(client, bob, fit_id, "wear")
    cast(client, bob, fit_id, "wear")

    assert get_fit(client, bob, fit_id)["votes"] == {"wear": 1, "rethink": 0}


def test_votes_from_several_users_add_up(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, create_user, post_fit
) -> None:
    fit_id = post_fit(jane)
    carol = create_user("carol")

    cast(client, jane, fit_id, "wear")
    cast(client, bob, fit_id, "wear")
    cast(client, carol, fit_id, "rethink")

    assert get_fit(client, jane, fit_id)["votes"] == {"wear": 2, "rethink": 1}


def test_author_may_vote_on_their_own_fit(
    client: TestClient, jane: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    assert cast(client, jane, fit_id, "wear").status_code == 200
    assert get_fit(client, jane, fit_id)["votes"]["wear"] == 1


def test_rejects_an_unknown_choice(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    response = cast(client, bob, fit_id, "maybe")

    assert response.status_code == 422
    assert get_fit(client, bob, fit_id)["votes"] == {"wear": 0, "rethink": 0}


# --- retracting ----------------------------------------------------------------------------


def test_retract_removes_the_vote(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)
    cast(client, bob, fit_id, "wear")

    response = client.delete(vote_url(fit_id), headers=bob.headers)

    assert response.status_code == 200, response.text
    assert response.json()["votes"] == {"wear": 0, "rethink": 0}
    assert response.json()["my_vote"] is None


def test_retract_without_voting_is_fine(
    client: TestClient, jane: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    assert client.delete(vote_url(fit_id), headers=jane.headers).status_code == 200


def test_retract_leaves_other_peoples_votes(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)
    cast(client, jane, fit_id, "wear")
    cast(client, bob, fit_id, "wear")

    client.delete(vote_url(fit_id), headers=bob.headers)

    assert get_fit(client, jane, fit_id)["votes"] == {"wear": 1, "rethink": 0}


# --- edges ---------------------------------------------------------------------------------


def test_unknown_fit_is_404(client: TestClient, jane: AuthedUser) -> None:
    assert cast(client, jane, UNKNOWN_FIT, "wear").status_code == 404
    assert client.delete(vote_url(UNKNOWN_FIT), headers=jane.headers).status_code == 404


def test_voting_requires_auth(client: TestClient, jane: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane)

    assert client.put(vote_url(fit_id), json={"choice": "wear"}).status_code == 401
    assert client.delete(vote_url(fit_id)).status_code == 401


def test_deleted_fit_cannot_be_voted_on(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    """Votes are cascaded away with the fit by the FK; what callers can see is
    that the fit, and so its votes, are gone.

    The rows themselves aren't asserted here: the test database is SQLite
    without `PRAGMA foreign_keys=ON`, so ON DELETE CASCADE doesn't fire there
    (the same is true of likes and saves).
    """
    fit_id = post_fit(jane)
    cast(client, bob, fit_id, "wear")

    assert client.delete(fit_url(fit_id), headers=jane.headers).status_code == 204
    assert client.get(fit_url(fit_id), headers=bob.headers).status_code == 404
    assert cast(client, bob, fit_id, "wear").status_code == 404


def test_votes_show_up_in_the_feed(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)
    cast(client, bob, fit_id, "wear")

    feed = client.get(FITS_URL, headers=bob.headers).json()
    entry = next(item for item in feed["items"] if item["id"] == fit_id)

    assert entry["votes"] == {"wear": 1, "rethink": 0}
    assert entry["my_vote"] == "wear"


def test_concurrent_first_vote_recovers(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit, monkeypatch
) -> None:
    """Two requests race to insert a first vote: one wins, the other updates."""
    from app.models.vote import FitVote
    from app.repositories import vote as vote_repository

    fit_id = post_fit(jane)
    cast(client, bob, fit_id, "wear")

    def always_insert(db, user_id, fit_id, choice) -> None:
        # As if the UPDATE found nothing because the other request hadn't committed.
        db.add(FitVote(user_id=user_id, fit_id=fit_id, choice=choice))
        db.flush()

    monkeypatch.setattr(vote_repository, "set_vote", always_insert)
    response = cast(client, bob, fit_id, "rethink")
    monkeypatch.undo()

    assert response.status_code == 200, response.text
    assert get_fit(client, bob, fit_id)["votes"] == {"wear": 0, "rethink": 1}
