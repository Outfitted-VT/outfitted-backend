from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AuthedUser

MESSAGES_URL = "/api/v1/messages"
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


def test_send_and_get_messages(client: TestClient, jane: AuthedUser, bob: AuthedUser, post_fit: Callable[[AuthedUser], str]):
    fit_id = post_fit(jane)

    # Bob sends Jane a message with attached fit
    res = client.post(
        f"{MESSAGES_URL}/jane",
        headers=bob.headers,
        json={"content": "Hey Jane, check this outfit!", "fit_id": fit_id},
    )
    assert res.status_code == 201
    msg_data = res.json()
    assert msg_data["content"] == "Hey Jane, check this outfit!"
    assert msg_data["sender"]["username"] == "bob"
    assert msg_data["recipient"]["username"] == "jane"
    assert msg_data["fit_id"] == fit_id
    assert msg_data["read_at"] is None

    # Jane checks threads
    threads_res = client.get(f"{MESSAGES_URL}/threads", headers=jane.headers)
    assert threads_res.status_code == 200
    threads = threads_res.json()
    assert len(threads) == 1
    assert threads[0]["partner"]["username"] == "bob"
    assert threads[0]["unread_count"] == 1
    assert threads[0]["last_message"]["content"] == "Hey Jane, check this outfit!"

    # Jane views the conversation history -> automatically marks as read
    conv_res = client.get(f"{MESSAGES_URL}/bob", headers=jane.headers)
    assert conv_res.status_code == 200
    messages = conv_res.json()
    assert len(messages) == 1
    assert messages[0]["read_at"] is not None

    # Jane replies
    reply_res = client.post(
        f"{MESSAGES_URL}/bob",
        headers=jane.headers,
        json={"content": "Love it! Trying it on right now."},
    )
    assert reply_res.status_code == 201

    # Bob views conversation
    bob_conv = client.get(f"{MESSAGES_URL}/jane", headers=bob.headers)
    assert bob_conv.status_code == 200
    assert len(bob_conv.json()) == 2
