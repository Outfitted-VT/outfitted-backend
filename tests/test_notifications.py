from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.mixins import utcnow
from app.services import notification as notification_service
from app.services.conversation import send_limiter
from tests.conftest import AuthedUser
from tests.test_conversations import connect, follow, next_event

URL = "/api/v1/notifications"
CONVERSATIONS_URL = "/api/v1/conversations"


@pytest.fixture(autouse=True)
def reset_rate_limit():
    send_limiter.reset()
    yield
    send_limiter.reset()


@pytest.fixture
def maya(create_user) -> AuthedUser:
    return create_user("maya", "Maya")


@pytest.fixture
def leo(create_user) -> AuthedUser:
    return create_user("leo", "Leo")


@pytest.fixture
def ivy(create_user) -> AuthedUser:
    return create_user("ivy", "Ivy")


def notifications(client: TestClient, user: AuthedUser, *kinds: str) -> list[dict]:
    response = client.get(URL, headers=user.headers)
    assert response.status_code == 200, response.text
    return [n for n in response.json()["items"] if not kinds or n["type"] in kinds]


def unread(client: TestClient, user: AuthedUser) -> int:
    return client.get(f"{URL}/unread-count", headers=user.headers).json()["unread"]


def post_fit(client: TestClient, user: AuthedUser, upload_image) -> str:
    response = client.post("/api/v1/fits", headers=user.headers, json={"image_ids": [upload_image(user)]})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def direct(client: TestClient, user: AuthedUser, other: AuthedUser) -> str:
    body = {"type": "direct", "member_ids": [str(other.id)]}
    return client.post(CONVERSATIONS_URL, headers=user.headers, json=body).json()["id"]


def send(client: TestClient, user: AuthedUser, conversation_id: str, **body) -> dict:
    body.setdefault("kind", "text")
    response = client.post(f"{CONVERSATIONS_URL}/{conversation_id}/messages", headers=user.headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_follow_notifies_with_text_and_link(client: TestClient, maya, leo) -> None:
    follow(client, leo, maya)
    follow(client, leo, maya)

    [item] = notifications(client, maya)
    assert item["type"] == "follow" and item["read"] is False
    assert (item["title"], item["body"], item["link"]) == ("New follower", "Leo started following you", "/users/leo")
    assert item["actor"]["username"] == "leo" and item["actor_count"] == 1
    assert item["data"] == {}
    assert notifications(client, leo) == []


def test_likes_on_one_fit_group_into_one_row(client: TestClient, create_user, maya, leo, ivy, upload_image) -> None:
    fit = post_fit(client, maya, upload_image)
    zed = create_user("zed", "Zed")
    for user in (leo, ivy, zed):
        client.put(f"/api/v1/fits/{fit}/like", headers=user.headers)
    client.delete(f"/api/v1/fits/{fit}/like", headers=leo.headers)
    client.put(f"/api/v1/fits/{fit}/like", headers=leo.headers)
    client.put(f"/api/v1/fits/{fit}/like", headers=maya.headers)

    [item] = [n for n in notifications(client, maya) if n["type"] == "like"]
    assert item["body"] == "Zed and 2 others liked your fit"
    assert item["title"] == "New likes" and item["actor_count"] == 3
    assert [a["username"] for a in item["actors"]] == ["zed", "ivy"]
    assert item["link"] == f"/fits/{fit}"


def test_grouping_window_is_24_hours(client: TestClient, monkeypatch, maya, leo, ivy, upload_image) -> None:
    fit = post_fit(client, maya, upload_image)
    client.put(f"/api/v1/fits/{fit}/like", headers=leo.headers)
    later = utcnow() + timedelta(hours=25)
    monkeypatch.setattr(notification_service, "utcnow", lambda: later)

    client.put(f"/api/v1/fits/{fit}/like", headers=ivy.headers)

    likes = [n for n in notifications(client, maya) if n["type"] == "like"]
    assert [n["body"] for n in likes] == ["Ivy liked your fit", "Leo liked your fit"]


def test_merged_row_comes_back_unread(client: TestClient, maya, leo, ivy, upload_image) -> None:
    fit = post_fit(client, maya, upload_image)
    client.put(f"/api/v1/fits/{fit}/like", headers=leo.headers)
    client.post(f"{URL}/read", headers=maya.headers, json={"all": True})
    assert unread(client, maya) == 0

    client.put(f"/api/v1/fits/{fit}/like", headers=ivy.headers)

    assert unread(client, maya) == 1


def test_comment_and_fit_vote(client: TestClient, maya, leo, ivy, upload_image) -> None:
    fit = post_fit(client, maya, upload_image)
    client.post(f"/api/v1/fits/{fit}/comments", headers=leo.headers, json={"content": "Love the jacket"})
    client.put(f"/api/v1/fits/{fit}/vote", headers=leo.headers, json={"option": 0})
    client.put(f"/api/v1/fits/{fit}/vote", headers=leo.headers, json={"option": 1})
    client.put(f"/api/v1/fits/{fit}/vote", headers=ivy.headers, json={"option": 0})

    by_type = {n["type"]: n for n in notifications(client, maya)}
    assert by_type["comment"]["body"] == "Leo commented: “Love the jacket”"
    assert by_type["fit_vote"]["body"] == "Ivy and 1 other voted on your fit"
    assert by_type["fit_vote"]["actor_count"] == 2


def test_message_notifies_only_offline_unmuted_members(client: TestClient, maya, leo) -> None:
    follow(client, maya, leo)
    chat = direct(client, maya, leo)
    send(client, maya, chat, body="you there?")

    [offline] = notifications(client, leo, "message")
    assert (offline["type"], offline["title"], offline["body"]) == ("message", "Maya", "you there?")
    assert offline["link"] == f"/conversations/{chat}"

    with client.websocket_connect("/api/v1/ws") as socket:
        connect(socket, leo)
        send(client, maya, chat, body="online now")
    client.patch(f"{CONVERSATIONS_URL}/{chat}", headers=leo.headers, json={"muted": True})
    send(client, maya, chat, body="muted")

    assert len(notifications(client, leo, "message")) == 1
    assert notifications(client, maya) == []


def test_circle_added_and_circle_message_title(client: TestClient, maya, leo, ivy) -> None:
    follow(client, maya, leo)
    follow(client, maya, ivy)
    body = {"type": "circle", "member_ids": [str(leo.id), str(ivy.id)], "title": "Weekend"}
    circle = client.post(CONVERSATIONS_URL, headers=maya.headers, json=body).json()["id"]
    send(client, maya, circle, body="Brunch?")

    latest, added = notifications(client, ivy, "message", "circle_added")
    assert added["type"] == "circle_added" and added["body"] == "Maya added you to Weekend"
    assert (latest["title"], latest["body"]) == ("Weekend", "Maya: Brunch?")


def test_fit_check_votes_notify_sender_unless_muted(client: TestClient, maya, leo, ivy, upload_image) -> None:
    follow(client, maya, leo)
    follow(client, maya, ivy)
    body = {"type": "circle", "member_ids": [str(leo.id), str(ivy.id)], "title": "Style"}
    circle = client.post(CONVERSATIONS_URL, headers=maya.headers, json=body).json()["id"]
    check = send(client, maya, circle, kind="fit_check", image_id=upload_image(maya), question="This one?")
    client.post(f"/api/v1/messages/{check['id']}/vote", headers=leo.headers, json={"vote": "wear"})
    client.post(f"/api/v1/messages/{check['id']}/vote", headers=leo.headers, json={"vote": "rethink"})

    votes = [n for n in notifications(client, maya) if n["type"] == "fit_check_vote"]
    assert [n["body"] for n in votes] == ["Leo voted on your fit check"]
    assert votes[0]["link"] == f"/conversations/{circle}?message={check['id']}"

    client.patch(f"{CONVERSATIONS_URL}/{circle}", headers=maya.headers, json={"muted": True})
    client.post(f"/api/v1/messages/{check['id']}/vote", headers=ivy.headers, json={"vote": "wear"})
    votes = [n for n in notifications(client, maya) if n["type"] == "fit_check_vote"]
    assert votes[0]["actor_count"] == 1


def test_story_reply_and_view_milestone(client: TestClient, create_user, maya, leo, upload_image) -> None:
    follow(client, maya, leo)
    story = client.post("/api/v1/stories", headers=maya.headers, json={"image_id": upload_image(maya)}).json()
    url = f"/api/v1/stories/{story['id']}/reply"
    client.post(url, headers=leo.headers, json={"body": "obsessed", "client_id": "r1"})
    client.post(url, headers=leo.headers, json={"body": "obsessed", "client_id": "r1"})
    for i in range(10):
        viewer = create_user(f"viewer{i}")
        client.post(f"/api/v1/stories/{story['id']}/view", headers=viewer.headers)

    by_type = {}
    for n in notifications(client, maya):
        by_type.setdefault(n["type"], []).append(n)
    [reply] = by_type["story_reply"]
    assert reply["body"] == "Leo replied to your story: “obsessed”"
    assert reply["link"].startswith("/conversations/")
    assert "message" not in by_type
    [milestone] = by_type["story_view_milestone"]
    assert milestone["body"] == "10 people have viewed your story"
    assert milestone["link"] == f"/stories/{story['id']}/viewers"


def test_pagination_and_mark_read(client: TestClient, create_user, maya) -> None:
    fans = [create_user(f"fan{i}") for i in range(5)]
    for fan in fans:
        follow(client, fan, maya)

    first = client.get(URL, headers=maya.headers, params={"limit": 3}).json()
    second = client.get(URL, headers=maya.headers, params={"limit": 3, "cursor": first["next_cursor"]}).json()
    items = first["items"] + second["items"]
    assert [n["actor"]["username"] for n in items] == [f.username for f in reversed(fans)]
    assert second["next_cursor"] is None
    assert client.get(URL, headers=maya.headers, params={"cursor": "bad"}).status_code == 400

    response = client.post(f"{URL}/read", headers=maya.headers, json={"ids": [items[0]["id"], items[1]["id"]]})
    assert response.json() == {"unread": 3}
    assert client.post(f"{URL}/read", headers=maya.headers, json={"all": True}).json() == {"unread": 0}
    assert client.post(f"{URL}/read", headers=maya.headers, json={}).status_code == 422
    assert client.post(f"{URL}/read", headers=maya.headers, json={"ids": [], "all": True}).status_code == 422


def test_cannot_read_someone_elses(client: TestClient, maya, leo) -> None:
    follow(client, leo, maya)
    [item] = notifications(client, maya)

    client.post(f"{URL}/read", headers=leo.headers, json={"ids": [item["id"]]})

    assert unread(client, maya) == 1


def test_realtime_new_and_count(client: TestClient, maya, leo) -> None:
    with client.websocket_connect("/api/v1/ws") as socket:
        connect(socket, maya)
        follow(client, leo, maya)
        new = next_event(socket, "notification:new")
        assert new["notification"]["type"] == "follow"
        assert next_event(socket, "notification:count") == {"type": "notification:count", "unread": 1}

        client.post(f"{URL}/read", headers=maya.headers, json={"all": True})
        assert next_event(socket, "notification:count") == {"type": "notification:count", "unread": 0}


def test_every_notification_is_queued_for_push(client: TestClient, push_queue, maya, leo) -> None:
    follow(client, leo, maya)

    [(fn, notification_id)] = push_queue.submitted
    assert fn is notification_service._deliver_in_background
    assert str(notification_id) == notifications(client, maya)[0]["id"]


def test_settings_defaults_and_update(client: TestClient, maya) -> None:
    url = "/api/v1/users/me/notification-settings"
    assert client.get(url, headers=maya.headers).json() == {
        "social": True,
        "messages": True,
        "stories": True,
        "streaks": True,
        "quiet_hours_start": None,
        "quiet_hours_end": None,
        "timezone": "UTC",
    }

    updated = client.patch(url, headers=maya.headers, json={"social": False, "quiet_hours_start": "22:00", "quiet_hours_end": "07:30"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["social"] is False and updated.json()["quiet_hours_start"] == "22:00:00"
    again = client.patch(url, headers=maya.headers, json={"messages": False}).json()
    assert (again["social"], again["messages"], again["quiet_hours_end"]) == (False, False, "07:30:00")
    cleared = client.patch(url, headers=maya.headers, json={"quiet_hours_start": None, "quiet_hours_end": None}).json()
    assert cleared["quiet_hours_start"] is None
    assert client.patch(url, headers=maya.headers, json={"quiet_hours_start": "22:00"}).status_code == 422
    assert client.patch(url, headers=maya.headers, json={"quiet_hours_start": "25:00", "quiet_hours_end": "07:00"}).status_code == 422


def test_requires_auth(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    assert client.get(f"{URL}/unread-count").status_code == 401
