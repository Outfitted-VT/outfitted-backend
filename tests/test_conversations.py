from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.services.conversation import send_limiter
from tests.conftest import AuthedUser

CONVERSATIONS_URL = "/api/v1/conversations"
MESSAGES_URL = "/api/v1/messages"
USERS_URL = "/api/v1/users"


@pytest.fixture(autouse=True)
def reset_rate_limit():
    send_limiter.reset()
    yield
    send_limiter.reset()


@pytest.fixture
def jane(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("jane", "Jane Doe")


@pytest.fixture
def bob(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("bob", "Bob Lee")


@pytest.fixture
def carol(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("carol")


def follow(client: TestClient, follower: AuthedUser, followee: AuthedUser) -> None:
    response = client.put(f"{USERS_URL}/{followee.username}/follow", headers=follower.headers)
    assert response.status_code == 204, response.text


@pytest.fixture
def circle(client: TestClient, jane: AuthedUser, bob: AuthedUser, carol: AuthedUser) -> None:
    """Jane follows Bob and Carol, so all three are in Jane's circle."""
    follow(client, jane, bob)
    follow(client, jane, carol)


def start(client: TestClient, user: AuthedUser, members: list[AuthedUser], kind="direct", title=None):
    body = {"type": kind, "member_ids": [str(m.id) for m in members], "title": title}
    return client.post(CONVERSATIONS_URL, headers=user.headers, json=body)


@pytest.fixture
def direct(client: TestClient, circle, jane: AuthedUser, bob: AuthedUser) -> str:
    response = start(client, jane, [bob])
    assert response.status_code == 201, response.text
    return response.json()["id"]


def send(client: TestClient, user: AuthedUser, conversation_id: str, **body):
    body.setdefault("kind", "text")
    return client.post(f"{CONVERSATIONS_URL}/{conversation_id}/messages", headers=user.headers, json=body)


def text(client: TestClient, user: AuthedUser, conversation_id: str, body: str) -> dict:
    response = send(client, user, conversation_id, body=body)
    assert response.status_code == 201, response.text
    return response.json()


def inbox(client: TestClient, user: AuthedUser) -> list[dict]:
    response = client.get(CONVERSATIONS_URL, headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_direct_chat_requires_circle(client: TestClient, jane: AuthedUser, carol: AuthedUser) -> None:
    response = start(client, jane, [carol])

    assert response.status_code == 403
    assert response.json() == {"detail": "You can only chat with people in your circle"}


def test_circle_works_in_both_directions(client: TestClient, jane: AuthedUser, bob: AuthedUser) -> None:
    follow(client, jane, bob)

    assert start(client, bob, [jane]).status_code == 201


def test_direct_chat_is_reused(client: TestClient, direct: str, jane: AuthedUser, bob: AuthedUser) -> None:
    again = start(client, jane, [bob])
    from_bob = start(client, bob, [jane])

    assert again.status_code == 200 and again.json()["id"] == direct
    assert from_bob.status_code == 200 and from_bob.json()["id"] == direct


def test_direct_chat_needs_exactly_one_member(client: TestClient, circle, jane, bob, carol) -> None:
    assert start(client, jane, [bob, carol]).status_code == 422


def test_non_members_get_404(client: TestClient, direct: str, carol: AuthedUser) -> None:
    for response in (
        client.get(f"{CONVERSATIONS_URL}/{direct}", headers=carol.headers),
        client.get(f"{CONVERSATIONS_URL}/{direct}/messages", headers=carol.headers),
        send(client, carol, direct, body="hi"),
        client.post(f"{CONVERSATIONS_URL}/{direct}/read", headers=carol.headers),
        client.patch(f"{CONVERSATIONS_URL}/{direct}", headers=carol.headers, json={"muted": True}),
        client.delete(f"{CONVERSATIONS_URL}/{direct}", headers=carol.headers),
    ):
        assert response.status_code == 404, response.text
        assert response.json() == {"detail": "Conversation not found"}


def test_requires_auth(client: TestClient) -> None:
    assert client.get(CONVERSATIONS_URL).status_code == 401


def test_messages_paginate_newest_first(client: TestClient, direct: str, jane, bob) -> None:
    sent = [text(client, jane if i % 2 else bob, direct, f"message {i}")["id"] for i in range(35)]

    first = client.get(f"{CONVERSATIONS_URL}/{direct}/messages", headers=jane.headers).json()
    second = client.get(
        f"{CONVERSATIONS_URL}/{direct}/messages",
        headers=jane.headers,
        params={"before": first["next_cursor"]},
    ).json()

    assert [m["id"] for m in first["items"]] == sent[::-1][:30]
    assert [m["id"] for m in second["items"]] == sent[::-1][30:]
    assert second["next_cursor"] is None


def test_invalid_cursor(client: TestClient, direct: str, jane) -> None:
    response = client.get(
        f"{CONVERSATIONS_URL}/{direct}/messages", headers=jane.headers, params={"before": "nope"}
    )
    assert response.status_code == 400


def test_text_is_validated_and_cleaned(client: TestClient, direct: str, jane) -> None:
    assert send(client, jane, direct, body="x" * 2001).status_code == 422
    assert send(client, jane, direct, body="   ").status_code == 422
    assert send(client, jane, direct, kind="video", body="hi").status_code == 422

    message = text(client, jane, direct, "  hi​ there\u0007\nfriend ")
    assert message["body"] == "hi there\nfriend"
    assert message["sender"]["username"] == "jane"


def test_client_id_makes_sends_idempotent(client: TestClient, direct: str, jane) -> None:
    first = send(client, jane, direct, body="once", client_id="abc-1").json()
    retry = send(client, jane, direct, body="once", client_id="abc-1").json()

    assert retry["id"] == first["id"]
    assert len(client.get(f"{CONVERSATIONS_URL}/{direct}/messages", headers=jane.headers).json()["items"]) == 1


def test_sends_are_rate_limited(client: TestClient, direct: str, jane) -> None:
    for i in range(20):
        text(client, jane, direct, f"{i}")

    response = send(client, jane, direct, body="one too many")
    assert response.status_code == 429
    assert response.json() == {"detail": "You're sending messages too fast. Wait a moment."}


def test_image_messages_need_your_own_image(client: TestClient, direct: str, jane, bob, upload_image) -> None:
    mine = send(client, jane, direct, kind="image", image_id=upload_image(jane))
    theirs = send(client, jane, direct, kind="image", image_id=upload_image(bob))

    assert mine.status_code == 201
    assert mine.json()["payload"]["image"]["url"].endswith(".webp")
    assert theirs.status_code == 400


def test_product_message(client: TestClient, direct: str, jane) -> None:
    product = {"name": "Chunky Loafers", "color": "Black", "price": "$320", "url": "https://shop.example/loafers"}
    message = send(client, jane, direct, kind="product", body="Or these?", product=product).json()

    assert message["payload"]["product"]["name"] == "Chunky Loafers"
    assert message["payload"]["product"]["image"] is None
    assert send(client, jane, direct, kind="product", product={**product, "url": "javascript:x"}).status_code == 422


def test_unread_counts_and_read_receipts(client: TestClient, direct: str, jane, bob) -> None:
    text(client, bob, direct, "one")
    last = text(client, bob, direct, "two")

    [row] = inbox(client, jane)
    assert row["unread_count"] == 2
    assert row["last_message"]["id"] == last["id"]
    assert inbox(client, bob)[0]["unread_count"] == 0

    receipt = client.post(f"{CONVERSATIONS_URL}/{direct}/read", headers=jane.headers).json()
    assert receipt["type"] == "receipt:update" and receipt["last_read_at"]

    assert inbox(client, jane)[0]["unread_count"] == 0
    members = {m["user"]["username"]: m for m in inbox(client, bob)[0]["members"]}
    assert members["jane"]["last_read_at"] >= last["created_at"]


def test_delivered_acknowledgement(client: TestClient, direct: str, jane, bob) -> None:
    text(client, bob, direct, "ping")
    response = client.post(f"{CONVERSATIONS_URL}/{direct}/delivered", headers=jane.headers)

    assert response.status_code == 200
    members = {m["user"]["username"]: m for m in inbox(client, bob)[0]["members"]}
    assert members["jane"]["last_delivered_at"] is not None
    assert members["jane"]["last_read_at"] is None


@pytest.fixture
def fit_check(client: TestClient, direct: str, jane, upload_image) -> dict:
    response = send(
        client, jane, direct, kind="fit_check", image_id=upload_image(jane),
        question="Too dressed up?", context="Vernissage · 18°C",
    )
    assert response.status_code == 201, response.text
    return response.json()


def vote(client: TestClient, user: AuthedUser, message_id: str, choice: str):
    return client.post(f"{MESSAGES_URL}/{message_id}/vote", headers=user.headers, json={"vote": choice})


def test_fit_check_votes(client: TestClient, fit_check: dict, jane, bob) -> None:
    assert fit_check["votes"] == {"wear": 0, "rethink": 0, "total": 0, "wear_pct": 0, "rethink_pct": 0, "my_vote": None}
    assert fit_check["payload"]["question"] == "Too dressed up?"

    vote(client, jane, fit_check["id"], "wear")
    result = vote(client, bob, fit_check["id"], "rethink").json()
    assert (result["wear"], result["rethink"], result["wear_pct"], result["rethink_pct"]) == (1, 1, 50, 50)
    assert result["my_vote"] == "rethink"

    changed = vote(client, bob, fit_check["id"], "wear").json()
    assert (changed["wear"], changed["rethink"], changed["wear_pct"]) == (2, 0, 100)


def test_votes_show_in_history_with_my_vote(client: TestClient, fit_check: dict, direct: str, jane, bob) -> None:
    vote(client, bob, fit_check["id"], "rethink")

    [message] = client.get(f"{CONVERSATIONS_URL}/{direct}/messages", headers=bob.headers).json()["items"]
    assert message["votes"]["my_vote"] == "rethink"
    assert message["votes"]["rethink_pct"] == 100


def test_vote_rules(client: TestClient, fit_check: dict, direct: str, jane, carol) -> None:
    plain = text(client, jane, direct, "hello")

    assert vote(client, carol, fit_check["id"], "wear").status_code == 404
    assert vote(client, jane, plain["id"], "wear").status_code == 400
    assert vote(client, jane, fit_check["id"], "maybe").status_code == 422


def test_only_the_sender_can_delete(client: TestClient, direct: str, jane, bob, carol) -> None:
    message = text(client, jane, direct, "oops")

    assert client.delete(f"{MESSAGES_URL}/{message['id']}", headers=bob.headers).status_code == 403
    assert client.delete(f"{MESSAGES_URL}/{message['id']}", headers=carol.headers).status_code == 404
    assert client.delete(f"{MESSAGES_URL}/{message['id']}", headers=jane.headers).status_code == 204

    [stored] = client.get(f"{CONVERSATIONS_URL}/{direct}/messages", headers=bob.headers).json()["items"]
    assert stored["deleted_at"] is not None
    assert stored["body"] is None and stored["payload"] is None


def test_circle_rename_mute_and_leave(client: TestClient, circle, jane, bob, carol) -> None:
    created = start(client, jane, [bob, carol], kind="circle", title="Gallery night").json()
    conversation_id = created["id"]
    assert created["type"] == "circle" and len(created["members"]) == 3

    renamed = client.patch(
        f"{CONVERSATIONS_URL}/{conversation_id}", headers=bob.headers, json={"title": "Gallery night 2"}
    ).json()
    assert renamed["title"] == "Gallery night 2"

    muted = client.patch(f"{CONVERSATIONS_URL}/{conversation_id}", headers=bob.headers, json={"muted": True}).json()
    assert muted["muted"] is True
    assert inbox(client, jane)[0]["muted"] is False

    assert client.delete(f"{CONVERSATIONS_URL}/{conversation_id}", headers=bob.headers).status_code == 204
    assert inbox(client, bob) == []
    assert len(inbox(client, jane)[0]["members"]) == 2


def test_direct_chats_cannot_be_renamed(client: TestClient, direct: str, jane) -> None:
    response = client.patch(f"{CONVERSATIONS_URL}/{direct}", headers=jane.headers, json={"title": "x"})
    assert response.status_code == 400


def test_hidden_direct_chat_returns_with_a_new_message(client: TestClient, direct: str, jane, bob) -> None:
    text(client, bob, direct, "hi")
    assert client.delete(f"{CONVERSATIONS_URL}/{direct}", headers=jane.headers).status_code == 204
    assert inbox(client, jane) == []

    text(client, bob, direct, "still there?")
    assert [c["id"] for c in inbox(client, jane)] == [direct]


def test_user_search_scoped_to_circle(client: TestClient, jane, bob, carol) -> None:
    follow(client, bob, jane)

    everyone = client.get(f"{USERS_URL}/search", headers=jane.headers).json()
    in_circle = client.get(f"{USERS_URL}/search", headers=jane.headers, params={"scope": "circle"}).json()

    assert {u["username"] for u in everyone} == {"bob", "carol"}
    assert [u["username"] for u in in_circle] == ["bob"]


def test_circle_people(client: TestClient, circle, jane) -> None:
    people = client.get(f"{CONVERSATIONS_URL}/circle", headers=jane.headers).json()

    assert {p["user"]["username"] for p in people} == {"bob", "carol"}
    assert all(p["online"] is False and p["has_live_fit_check"] is False for p in people)


def test_suggestions_rank_mutuals_first(client: TestClient, create_user, jane, bob, carol) -> None:
    dave = create_user("dave")
    follow(client, jane, bob)
    follow(client, bob, carol)

    suggestions = client.get(f"{USERS_URL}/suggestions", headers=jane.headers).json()

    assert [s["username"] for s in suggestions] == ["carol", "dave"]
    assert suggestions[0]["mutual_count"] == 1


def test_style_profile_is_saved(client: TestClient, jane) -> None:
    profile = {
        "style_tags": ["minimal", "tailored", "minimal"],
        "fit_preference": "relaxed",
        "top_size": "S",
        "bottom_size": "M",
        "feedback_tone": "kind",
    }
    response = client.patch(f"{USERS_URL}/me", headers=jane.headers, json=profile)

    assert response.status_code == 200, response.text
    me = client.get(f"{USERS_URL}/me", headers=jane.headers).json()
    assert me["style_tags"] == ["minimal", "tailored"]
    assert (me["fit_preference"], me["top_size"], me["bottom_size"], me["feedback_tone"]) == ("relaxed", "S", "M", "kind")
    assert client.patch(f"{USERS_URL}/me", headers=jane.headers, json={"top_size": "XXL"}).status_code == 422


def connect(socket, user: AuthedUser) -> None:
    socket.send_json({"type": "auth", "token": user.headers["Authorization"].removeprefix("Bearer ")})
    assert socket.receive_json()["type"] == "ready"


def test_socket_rejects_bad_tokens(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws") as socket:
        socket.send_json({"type": "auth", "token": "not-a-token"})
        with pytest.raises(WebSocketDisconnect) as error:
            socket.receive_json()
    assert error.value.code == 4401


def test_socket_pushes_messages_votes_receipts_and_typing(client: TestClient, direct: str, jane, bob, upload_image) -> None:
    with client.websocket_connect("/api/v1/ws") as socket:
        connect(socket, bob)

        sent = text(client, jane, direct, "live?")
        event = socket.receive_json()
        assert event["type"] == "message:new" and event["message"]["id"] == sent["id"]

        client.post(f"{CONVERSATIONS_URL}/{direct}/read", headers=bob.headers)
        receipt = socket.receive_json()
        assert receipt["type"] == "receipt:update" and receipt["user_id"] == str(bob.id)

        check = send(client, jane, direct, kind="fit_check", image_id=upload_image(jane), question="Yes?").json()
        assert socket.receive_json()["type"] == "message:new"
        vote(client, jane, check["id"], "wear")
        update = socket.receive_json()
        assert update["type"] == "vote:update" and update["wear_pct"] == 100 and "my_vote" not in update

        client.delete(f"{MESSAGES_URL}/{sent['id']}", headers=jane.headers)
        assert socket.receive_json() == {"type": "message:deleted", "conversation_id": direct, "message_id": sent["id"]}

        with client.websocket_connect("/api/v1/ws") as other:
            connect(other, jane)
            other.send_json({"type": "typing:start", "conversation_id": direct})
            typing = socket.receive_json()
            while typing["type"] == "presence:update":
                typing = socket.receive_json()
            assert typing == {"type": "typing:start", "conversation_id": direct, "user_id": str(jane.id)}


def test_presence_and_last_seen(client: TestClient, direct: str, jane, bob) -> None:
    with client.websocket_connect("/api/v1/ws") as socket:
        connect(socket, jane)
        members = {m["user"]["username"]: m for m in inbox(client, bob)[0]["members"]}
        assert members["jane"]["online"] is True

    members = {m["user"]["username"]: m for m in inbox(client, bob)[0]["members"]}
    assert members["jane"]["online"] is False
    assert members["jane"]["last_seen_at"] is not None


def test_typing_is_ignored_for_non_members(client: TestClient, direct: str, jane, carol) -> None:
    with client.websocket_connect("/api/v1/ws") as socket:
        connect(socket, jane)
        with client.websocket_connect("/api/v1/ws") as outsider:
            connect(outsider, carol)
            outsider.send_json({"type": "typing:start", "conversation_id": direct})
            outsider.send_json({"type": "ping"})
            assert outsider.receive_json() == {"type": "pong"}
        text(client, jane, direct, "after")
        assert socket.receive_json()["type"] == "message:new"


def test_client_id_reused_in_another_conversation_conflicts(client: TestClient, direct: str, circle, jane, bob, carol) -> None:
    other = start(client, jane, [carol]).json()["id"]
    assert send(client, jane, direct, body="first", client_id="c-1").status_code == 201

    response = send(client, jane, other, body="second", client_id="c-1")

    assert response.status_code == 409


def test_socket_releases_its_transaction(client: TestClient, direct: str, jane, db) -> None:
    with client.websocket_connect("/api/v1/ws") as socket:
        connect(socket, jane)
        socket.send_json({"type": "typing:start", "conversation_id": direct})
        socket.send_json({"type": "ping"})
        assert socket.receive_json() == {"type": "pong"}
        assert not db.in_transaction()


def next_event(socket, kind: str) -> dict:
    while (event := socket.receive_json())["type"] != kind:
        pass
    return event


def test_typing_stops_after_leaving_a_circle(client: TestClient, circle, jane, bob, carol) -> None:
    conversation_id = start(client, jane, [bob, carol], kind="circle", title="Trip").json()["id"]
    with client.websocket_connect("/api/v1/ws") as socket:
        connect(socket, jane)
        with client.websocket_connect("/api/v1/ws") as leaver:
            connect(leaver, bob)
            leaver.send_json({"type": "typing:start", "conversation_id": conversation_id})
            assert next_event(socket, "typing:start")["user_id"] == str(bob.id)
            client.delete(f"{CONVERSATIONS_URL}/{conversation_id}", headers=bob.headers)
            leaver.send_json({"type": "typing:stop", "conversation_id": conversation_id})
            leaver.send_json({"type": "ping"})
            next_event(leaver, "pong")
        text(client, jane, conversation_id, "after")
        seen = []
        while (event := socket.receive_json())["type"] != "message:new":
            seen.append(event["type"])
        assert "typing:stop" not in seen
