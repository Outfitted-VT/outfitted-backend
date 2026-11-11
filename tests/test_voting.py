from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AuthedUser

FITS_URL = "/api/v1/fits"
UNKNOWN_FIT = "00000000-0000-0000-0000-000000000000"
WEAR, RETHINK = 0, 1  # the default poll's answers

RATE_IT = {"question": "Rate this fit", "options": ["Fire", "Solid", "Meh"]}


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
) -> Callable[..., str]:
    """Posts a fit. Pass poll=... to send one; left out, the fit gets the default poll."""

    def _post_fit(user: AuthedUser, **fields) -> str:
        response = client.post(
            FITS_URL, headers=user.headers, json={"image_ids": [upload_image(user)], **fields}
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    return _post_fit


def get_fit(client: TestClient, user: AuthedUser, fit_id: str) -> dict:
    return client.get(fit_url(fit_id), headers=user.headers).json()


def cast(client: TestClient, user: AuthedUser, fit_id: str, option: int):
    return client.put(vote_url(fit_id), headers=user.headers, json={"option": option})


def tallies(fit: dict) -> list[int]:
    return [option["votes"] for option in fit["poll"]["options"]]


# --- the poll -------------------------------------------------------------------------------


def test_new_fit_gets_the_default_poll(client: TestClient, jane: AuthedUser, post_fit) -> None:
    poll = get_fit(client, jane, post_fit(jane))["poll"]

    assert poll == {
        "question": "Would you wear it?",
        "options": [{"label": "Wear it", "votes": 0}, {"label": "Rethink", "votes": 0}],
        "total_votes": 0,
        "my_vote": None,
        "locked": False,
    }


def test_poster_picks_the_poll(client: TestClient, jane: AuthedUser, post_fit) -> None:
    poll = get_fit(client, jane, post_fit(jane, poll=RATE_IT))["poll"]

    assert poll["question"] == "Rate this fit"
    assert [option["label"] for option in poll["options"]] == ["Fire", "Solid", "Meh"]


def test_poll_text_is_trimmed(client: TestClient, jane: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane, poll={"question": "  Keep it?  ", "options": [" Keep ", "Return"]})
    poll = get_fit(client, jane, fit_id)["poll"]

    assert poll["question"] == "Keep it?"
    assert poll["options"][0]["label"] == "Keep"


def test_fit_without_a_poll(client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane, poll=None)

    assert get_fit(client, jane, fit_id)["poll"] is None
    response = cast(client, bob, fit_id, 0)
    assert response.status_code == 409
    assert response.json() == {"detail": "This fit has no poll"}


@pytest.mark.parametrize(
    "poll",
    [
        {"question": "Only one?", "options": ["Yes"]},
        {"question": "Too many?", "options": ["a", "b", "c", "d", "e"]},
        {"question": "Twice?", "options": ["Same", "same"]},
        {"question": "", "options": ["a", "b"]},
        {"question": "Blank answer?", "options": ["a", "   "]},
        {"question": "x" * 101, "options": ["a", "b"]},
        {"question": "Long answer?", "options": ["a", "b" * 31]},
    ],
)
def test_rejects_a_bad_poll(
    client: TestClient, jane: AuthedUser, upload_image, poll: dict
) -> None:
    response = client.post(
        FITS_URL, headers=jane.headers, json={"image_ids": [upload_image(jane)], "poll": poll}
    )

    assert response.status_code == 422


def test_poll_can_change_until_someone_votes(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    response = client.patch(fit_url(fit_id), headers=jane.headers, json={"poll": RATE_IT})

    assert response.status_code == 200, response.text
    assert response.json()["poll"]["question"] == "Rate this fit"

    cast(client, bob, fit_id, 2)
    assert get_fit(client, jane, fit_id)["poll"]["locked"] is True

    for change in ({"question": "Rate it", "options": ["Fire", "Meh"]}, None):
        response = client.patch(fit_url(fit_id), headers=jane.headers, json={"poll": change})
        assert response.status_code == 409
        assert response.json() == {"detail": "The poll can't change after people have voted"}
    assert get_fit(client, jane, fit_id)["poll"]["question"] == "Rate this fit"


def test_editing_other_fields_leaves_a_voted_poll_alone(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)
    cast(client, bob, fit_id, WEAR)

    caption = client.patch(fit_url(fit_id), headers=jane.headers, json={"caption": "New caption"})
    same_poll = client.patch(
        fit_url(fit_id),
        headers=jane.headers,
        json={"poll": {"question": "Would you wear it?", "options": ["Wear it", "Rethink"]}},
    )

    assert caption.status_code == 200
    assert same_poll.status_code == 200
    assert tallies(same_poll.json()) == [1, 0]


def test_poll_can_be_removed_before_votes(client: TestClient, jane: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane)

    response = client.patch(fit_url(fit_id), headers=jane.headers, json={"poll": None})

    assert response.status_code == 200
    assert response.json()["poll"] is None


# --- casting -------------------------------------------------------------------------------


def test_vote_is_counted_and_returned(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    response = cast(client, bob, fit_id, WEAR)

    assert response.status_code == 200, response.text
    # The response carries the new tallies, so the client needn't refetch.
    assert tallies(response.json()) == [1, 0]
    assert response.json()["poll"]["my_vote"] == WEAR
    assert response.json()["poll"]["total_votes"] == 1
    assert tallies(get_fit(client, bob, fit_id)) == [1, 0]


def test_votes_on_a_custom_poll(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, create_user, post_fit
) -> None:
    fit_id = post_fit(jane, poll=RATE_IT)
    carol = create_user("carol")

    cast(client, bob, fit_id, 2)
    cast(client, carol, fit_id, 2)
    cast(client, jane, fit_id, 0)

    assert tallies(get_fit(client, jane, fit_id)) == [1, 0, 2]


def test_my_vote_is_per_viewer(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)
    cast(client, bob, fit_id, RETHINK)

    assert get_fit(client, bob, fit_id)["poll"]["my_vote"] == RETHINK
    assert get_fit(client, jane, fit_id)["poll"]["my_vote"] is None
    # ...but the tallies are the same for everyone.
    assert tallies(get_fit(client, jane, fit_id)) == [0, 1]


def test_changing_your_vote_replaces_it(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    cast(client, bob, fit_id, WEAR)
    response = cast(client, bob, fit_id, RETHINK)

    assert tallies(response.json()) == [0, 1]
    assert response.json()["poll"]["my_vote"] == RETHINK


def test_voting_twice_the_same_way_is_idempotent(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    cast(client, bob, fit_id, WEAR)
    cast(client, bob, fit_id, WEAR)

    assert tallies(get_fit(client, bob, fit_id)) == [1, 0]


def test_author_may_vote_on_their_own_fit(
    client: TestClient, jane: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    assert cast(client, jane, fit_id, WEAR).status_code == 200
    assert tallies(get_fit(client, jane, fit_id)) == [1, 0]


def test_rejects_an_answer_past_the_end(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    response = cast(client, bob, fit_id, 2)

    assert response.status_code == 400
    assert response.json() == {"detail": "No such poll answer"}
    assert cast(client, bob, fit_id, -1).status_code == 422
    assert client.put(vote_url(fit_id), headers=bob.headers, json={"choice": "wear"}).status_code == 422
    assert tallies(get_fit(client, bob, fit_id)) == [0, 0]


# --- retracting ----------------------------------------------------------------------------


def test_retract_removes_the_vote(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)
    cast(client, bob, fit_id, WEAR)

    response = client.delete(vote_url(fit_id), headers=bob.headers)

    assert response.status_code == 200, response.text
    assert tallies(response.json()) == [0, 0]
    assert response.json()["poll"]["my_vote"] is None


def test_retract_without_voting_is_fine(
    client: TestClient, jane: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)

    assert client.delete(vote_url(fit_id), headers=jane.headers).status_code == 200


def test_retract_leaves_other_peoples_votes(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)
    cast(client, jane, fit_id, WEAR)
    cast(client, bob, fit_id, WEAR)

    client.delete(vote_url(fit_id), headers=bob.headers)

    assert tallies(get_fit(client, jane, fit_id)) == [1, 0]


# --- edges ---------------------------------------------------------------------------------


def test_unknown_fit_is_404(client: TestClient, jane: AuthedUser) -> None:
    assert cast(client, jane, UNKNOWN_FIT, WEAR).status_code == 404
    assert client.delete(vote_url(UNKNOWN_FIT), headers=jane.headers).status_code == 404


def test_voting_requires_auth(client: TestClient, jane: AuthedUser, post_fit) -> None:
    fit_id = post_fit(jane)

    assert client.put(vote_url(fit_id), json={"option": WEAR}).status_code == 401
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
    cast(client, bob, fit_id, WEAR)

    assert client.delete(fit_url(fit_id), headers=jane.headers).status_code == 204
    assert client.get(fit_url(fit_id), headers=bob.headers).status_code == 404
    assert cast(client, bob, fit_id, WEAR).status_code == 404


def test_votes_show_up_in_the_feed(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit
) -> None:
    fit_id = post_fit(jane)
    cast(client, bob, fit_id, WEAR)

    feed = client.get(FITS_URL, headers=bob.headers).json()
    entry = next(item for item in feed["items"] if item["id"] == fit_id)

    assert tallies(entry) == [1, 0]
    assert entry["poll"]["my_vote"] == WEAR


def test_concurrent_first_vote_recovers(
    client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit, monkeypatch
) -> None:
    """Two requests race to insert a first vote: one wins, the other updates."""
    from app.models.vote import FitVote
    from app.repositories import vote as vote_repository

    fit_id = post_fit(jane)
    cast(client, bob, fit_id, WEAR)

    def always_insert(db, user_id, fit_id, option) -> None:
        # As if the UPDATE found nothing because the other request hadn't committed.
        db.add(FitVote(user_id=user_id, fit_id=fit_id, option=option))
        db.flush()

    monkeypatch.setattr(vote_repository, "set_vote", always_insert)
    response = cast(client, bob, fit_id, RETHINK)
    monkeypatch.undo()

    assert response.status_code == 200, response.text
    assert tallies(get_fit(client, bob, fit_id)) == [0, 1]
