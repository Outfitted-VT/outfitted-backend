import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.mixins import utcnow
from app.models.image import Image
from app.models.story import Story
from app.services import story as story_service
from app.services.conversation import send_limiter
from tests.conftest import AuthedUser
from tests.test_conversations import connect, follow, next_event

STORIES_URL = "/api/v1/stories"
CONVERSATIONS_URL = "/api/v1/conversations"


@pytest.fixture(autouse=True)
def reset_rate_limit():
    send_limiter.reset()
    yield
    send_limiter.reset()


@pytest.fixture
def clock(monkeypatch):
    """Shift the stories clock forward with clock.advance(timedelta)."""

    class Clock:
        offset = timedelta()

        def now(self):
            return utcnow() + self.offset

        def advance(self, delta: timedelta) -> None:
            self.offset += delta

    frozen = Clock()
    monkeypatch.setattr(story_service, "utcnow", frozen.now)
    return frozen


@pytest.fixture
def maya(create_user) -> AuthedUser:
    return create_user("maya")


@pytest.fixture
def leo(create_user) -> AuthedUser:
    return create_user("leo")


@pytest.fixture
def ivy(create_user) -> AuthedUser:
    return create_user("ivy")


@pytest.fixture
def friends(client: TestClient, maya, leo, ivy) -> None:
    """Maya and Leo follow each other (close friends). Ivy follows Maya one way."""
    follow(client, maya, leo)
    follow(client, leo, maya)
    follow(client, ivy, maya)


def post(client: TestClient, user: AuthedUser, image_id: str, **body):
    return client.post(STORIES_URL, headers=user.headers, json={"image_id": image_id, **body})


def story(client: TestClient, user: AuthedUser, upload_image, **body) -> dict:
    response = post(client, user, upload_image(user), **body)
    assert response.status_code == 201, response.text
    return response.json()


def feed(client: TestClient, user: AuthedUser) -> list[dict]:
    response = client.get(f"{STORIES_URL}/feed", headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()


def view(client: TestClient, user: AuthedUser, story_id: str):
    return client.post(f"{STORIES_URL}/{story_id}/view", headers=user.headers)


def test_post_story(client: TestClient, maya, upload_image) -> None:
    created = story(client, maya, upload_image, caption="  Sunday fit  ")

    assert created["caption"] == "Sunday fit"
    assert created["visibility"] == "public"
    assert created["seen"] is True and created["view_count"] == 0
    assert created["image"]["url"]


def test_story_validation(client: TestClient, maya, leo, upload_image) -> None:
    image = upload_image(maya)

    assert post(client, maya, image, caption="x" * 201).status_code == 422
    assert post(client, maya, image, visibility="vault").status_code == 422
    assert post(client, leo, image).status_code == 400
    assert client.post(STORIES_URL, json={"image_id": image}).status_code == 401


def test_story_fit_must_be_yours_and_not_vault(client: TestClient, maya, leo, upload_image) -> None:
    def fit(user, tier):
        body = {"image_ids": [upload_image(user)], "privacy_tier": tier}
        return client.post("/api/v1/fits", headers=user.headers, json=body).json()["id"]

    image = upload_image(maya)
    assert post(client, maya, image, fit_id=fit(maya, "public")).status_code == 201
    assert post(client, maya, image, fit_id=fit(maya, "vault")).status_code == 400
    assert post(client, maya, image, fit_id=fit(leo, "public")).status_code == 400


def test_at_most_20_active_stories(client: TestClient, maya, upload_image, clock) -> None:
    image = upload_image(maya)
    for _ in range(20):
        assert post(client, maya, image).status_code == 201

    assert post(client, maya, image).status_code == 409
    clock.advance(timedelta(hours=25))
    assert post(client, maya, image).status_code == 201


def test_close_friends_hidden_from_non_close_friends(client: TestClient, friends, maya, leo, ivy, upload_image) -> None:
    public = story(client, maya, upload_image)
    private = story(client, maya, upload_image, visibility="close_friends")

    def visible(user):
        groups = feed(client, user)
        return [s["id"] for g in groups for s in g["stories"]]

    assert visible(leo) == [public["id"], private["id"]]
    assert visible(ivy) == [public["id"]]
    profile = client.get(f"/api/v1/users/{maya.id}/stories", headers=ivy.headers).json()
    assert [s["id"] for s in profile["stories"]] == [public["id"]]
    assert view(client, ivy, private["id"]).status_code == 404
    assert client.post(f"{STORIES_URL}/{private['id']}/reply", headers=ivy.headers, json={"body": "hi"}).status_code == 404


def test_feed_only_shows_your_circle(client: TestClient, maya, leo, upload_image) -> None:
    story(client, maya, upload_image)

    assert feed(client, leo) == []
    profile = client.get(f"/api/v1/users/{maya.id}/stories", headers=leo.headers).json()
    assert len(profile["stories"]) == 1


def test_stories_expire_after_24_hours(client: TestClient, friends, maya, leo, upload_image, clock) -> None:
    posted = story(client, maya, upload_image)
    clock.advance(timedelta(hours=23, minutes=59))
    assert len(feed(client, leo)) == 1

    clock.advance(timedelta(minutes=2))

    assert feed(client, leo) == []
    assert view(client, leo, posted["id"]).status_code == 404
    assert client.get(f"/api/v1/users/{maya.id}/stories", headers=leo.headers).json()["stories"] == []


def test_view_is_idempotent_and_owner_views_dont_count(client: TestClient, friends, maya, leo, upload_image) -> None:
    posted = story(client, maya, upload_image)

    assert view(client, leo, posted["id"]).status_code == 204
    assert view(client, leo, posted["id"]).status_code == 204
    assert view(client, maya, posted["id"]).status_code == 204

    [mine] = feed(client, maya)
    assert mine["stories"][0]["view_count"] == 1
    [theirs] = feed(client, leo)
    assert theirs["has_unseen"] is False and theirs["stories"][0]["seen"] is True
    assert theirs["stories"][0]["view_count"] is None


def test_viewers_owner_only_newest_first(client: TestClient, create_user, friends, maya, leo, ivy, upload_image, clock) -> None:
    posted = story(client, maya, upload_image)
    viewers = [leo, ivy] + [create_user(f"fan{i}") for i in range(3)]
    for user in viewers:
        clock.advance(timedelta(seconds=1))
        view(client, user, posted["id"])

    url = f"{STORIES_URL}/{posted['id']}/viewers"
    first = client.get(url, headers=maya.headers, params={"limit": 3}).json()
    second = client.get(url, headers=maya.headers, params={"limit": 3, "cursor": first["next_cursor"]}).json()

    names = [v["user"]["username"] for v in first["items"] + second["items"]]
    assert names == [u.username for u in reversed(viewers)]
    assert second["next_cursor"] is None
    assert client.get(url, headers=leo.headers).status_code == 403
    assert client.get(url, headers=maya.headers, params={"cursor": "bad"}).status_code == 400


def test_delete_is_owner_only_and_soft(client: TestClient, db, friends, maya, leo, upload_image) -> None:
    posted = story(client, maya, upload_image)

    assert client.delete(f"{STORIES_URL}/{posted['id']}", headers=leo.headers).status_code == 403
    assert client.delete(f"{STORIES_URL}/{posted['id']}", headers=maya.headers).status_code == 204

    assert feed(client, leo) == [] and feed(client, maya) == []
    assert client.delete(f"{STORIES_URL}/{posted['id']}", headers=maya.headers).status_code == 404
    assert db.get(Story, uuid.UUID(posted["id"])) is not None


def test_reply_creates_then_reuses_direct_chat(client: TestClient, friends, maya, leo, upload_image) -> None:
    posted = story(client, maya, upload_image, caption="New jacket")
    url = f"{STORIES_URL}/{posted['id']}/reply"

    first = client.post(url, headers=leo.headers, json={"body": "Love it"})
    second = client.post(url, headers=leo.headers, json={"body": "Where from?"})

    assert first.status_code == 201, first.text
    message = first.json()
    assert message["kind"] == "story_reply" and message["body"] == "Love it"
    assert message["payload"]["story_id"] == posted["id"]
    assert message["payload"]["caption"] == "New jacket"
    assert message["payload"]["image"]["id"] == posted["image"]["id"]
    assert second.json()["conversation_id"] == message["conversation_id"]
    inbox = client.get(CONVERSATIONS_URL, headers=maya.headers).json()
    assert [c["id"] for c in inbox] == [message["conversation_id"]]
    assert inbox[0]["type"] == "direct" and inbox[0]["unread_count"] == 2


def test_reply_reuses_an_existing_direct_chat(client: TestClient, friends, maya, leo, upload_image) -> None:
    existing = client.post(
        CONVERSATIONS_URL, headers=maya.headers, json={"type": "direct", "member_ids": [str(leo.id)]}
    ).json()["id"]
    posted = story(client, maya, upload_image)

    reply = client.post(f"{STORIES_URL}/{posted['id']}/reply", headers=leo.headers, json={"body": "nice"}).json()

    assert reply["conversation_id"] == existing


def test_reply_rules(client: TestClient, friends, maya, leo, upload_image) -> None:
    posted = story(client, maya, upload_image)
    url = f"{STORIES_URL}/{posted['id']}/reply"

    assert client.post(url, headers=maya.headers, json={"body": "me"}).status_code == 400
    assert client.post(url, headers=leo.headers, json={"body": "   "}).status_code == 422
    send = {"kind": "story_reply", "body": "forged", "story_id": posted["id"]}
    conversation = client.post(
        CONVERSATIONS_URL, headers=leo.headers, json={"type": "direct", "member_ids": [str(maya.id)]}
    ).json()["id"]
    assert client.post(f"{CONVERSATIONS_URL}/{conversation}/messages", headers=leo.headers, json=send).status_code == 422


def test_feed_ordering(client: TestClient, create_user, maya, leo, ivy, upload_image, clock) -> None:
    zed = create_user("zed")
    for other in (leo, ivy, zed):
        follow(client, maya, other)

    def later(user):
        clock.advance(timedelta(minutes=1))
        return story(client, user, upload_image)["id"]

    leo_first = later(leo)
    ivy_first = later(ivy)
    later(zed)
    leo_second = later(leo)
    ivy_second = later(ivy)
    later(maya)
    view(client, maya, ivy_first)
    view(client, maya, ivy_second)

    groups = feed(client, maya)

    assert [g["user"]["username"] for g in groups] == ["maya", "leo", "zed", "ivy"]
    assert [g["has_unseen"] for g in groups] == [False, True, True, False]
    assert [s["id"] for s in groups[1]["stories"]] == [leo_first, leo_second]


def test_circle_shows_story_flags(client: TestClient, friends, maya, leo, ivy, upload_image) -> None:
    posted = story(client, leo, upload_image)
    story(client, maya, upload_image, visibility="close_friends")

    people = {p["user"]["username"]: p for p in client.get(f"{CONVERSATIONS_URL}/circle", headers=maya.headers).json()}
    assert (people["leo"]["has_active_story"], people["leo"]["has_unseen_story"]) == (True, True)
    assert (people["ivy"]["has_active_story"], people["ivy"]["has_unseen_story"]) == (False, False)

    view(client, maya, posted["id"])
    people = {p["user"]["username"]: p for p in client.get(f"{CONVERSATIONS_URL}/circle", headers=maya.headers).json()}
    assert (people["leo"]["has_active_story"], people["leo"]["has_unseen_story"]) == (True, False)
    ivy_circle = {p["user"]["username"]: p for p in client.get(f"{CONVERSATIONS_URL}/circle", headers=ivy.headers).json()}
    assert ivy_circle["maya"]["has_active_story"] is False


def test_realtime_story_new_and_viewed(client: TestClient, friends, maya, leo, ivy, upload_image) -> None:
    with client.websocket_connect("/api/v1/ws") as leo_socket, client.websocket_connect("/api/v1/ws") as maya_socket:
        connect(leo_socket, leo)
        connect(maya_socket, maya)
        posted = story(client, maya, upload_image)
        event = next_event(leo_socket, "story:new")
        assert event["story_id"] == posted["id"] and event["user"]["username"] == "maya"

        view(client, leo, posted["id"])
        viewed = next_event(maya_socket, "story:viewed")
        assert viewed == {
            "type": "story:viewed",
            "story_id": posted["id"],
            "viewer": viewed["viewer"],
            "view_count": 1,
        }
        assert viewed["viewer"]["username"] == "leo"


def test_cleanup_removes_old_stories_and_unused_images(client: TestClient, db, storage, friends, maya, leo, upload_image, clock) -> None:
    shared = upload_image(maya)
    fit = client.post("/api/v1/fits", headers=maya.headers, json={"image_ids": [shared]}).json()
    old_alone = story(client, maya, upload_image)
    old_shared = post(client, maya, shared).json()
    view(client, leo, old_alone["id"])
    client.post(f"{STORIES_URL}/{old_alone['id']}/reply", headers=leo.headers, json={"body": "nice"})
    lone_key = db.get(Image, uuid.UUID(old_alone["image"]["id"])).storage_key
    clock.advance(timedelta(days=7, hours=23))
    recent = story(client, maya, upload_image)

    assert story_service.cleanup_expired(db, storage, now=clock.now()) == 0
    clock.advance(timedelta(hours=2))
    assert story_service.cleanup_expired(db, storage, now=clock.now()) == 2

    db.expire_all()
    assert db.get(Story, uuid.UUID(old_alone["id"])) is None and db.get(Story, uuid.UUID(old_shared["id"])) is None
    assert db.get(Story, uuid.UUID(recent["id"])) is not None
    assert db.get(Image, uuid.UUID(old_alone["image"]["id"])) is None
    assert not (storage.root / lone_key).exists()
    assert db.get(Image, uuid.UUID(shared)) is not None
    assert client.get(f"/api/v1/fits/{fit['id']}", headers=maya.headers).status_code == 200
    conversation = client.get(CONVERSATIONS_URL, headers=leo.headers).json()[0]
    reply = conversation["last_message"]
    assert reply["kind"] == "story_reply" and reply["payload"]["image"] is None


def test_deleting_a_fit_keeps_a_photo_used_by_a_story(client: TestClient, db, friends, maya, upload_image) -> None:
    image = upload_image(maya)
    fit = client.post("/api/v1/fits", headers=maya.headers, json={"image_ids": [image]}).json()
    posted = post(client, maya, image).json()

    assert client.delete(f"/api/v1/fits/{fit['id']}", headers=maya.headers).status_code == 204

    db.expire_all()
    assert db.get(Image, uuid.UUID(image)) is not None
    assert feed(client, maya)[0]["stories"][0]["id"] == posted["id"]


def test_user_stories_unknown_user(client: TestClient, maya) -> None:
    response = client.get("/api/v1/users/00000000-0000-0000-0000-000000000000/stories", headers=maya.headers)
    assert response.status_code == 404
