import json
import uuid
from datetime import UTC, datetime, time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.jobs import create_scheduler
from app.models.device import DeviceToken
from app.models.notification import Notification
from app.push import (
    APNsSender,
    FCMSender,
    LogPushSender,
    PlatformSender,
    PushMessage,
    PushResult,
    get_push_sender,
    short_collapse_key,
)
from app.services import notification as notification_service
from app.services.notification import in_quiet_hours
from tests.conftest import AuthedUser
from tests.test_conversations import follow

DEVICES_URL = "/api/v1/devices"


class FakeSender:
    def __init__(self, invalid: set[str] = frozenset()) -> None:
        self.sent: list[PushMessage] = []
        self.invalid = invalid

    def send(self, message: PushMessage) -> PushResult:
        self.sent.append(message)
        return PushResult.INVALID_TOKEN if message.token in self.invalid else PushResult.SENT


@pytest.fixture
def maya(create_user) -> AuthedUser:
    return create_user("maya", "Maya")


@pytest.fixture
def leo(create_user) -> AuthedUser:
    return create_user("leo", "Leo")


def register(client: TestClient, user: AuthedUser, token: str, platform: str = "ios", version: str = "1.0"):
    return client.post(DEVICES_URL, headers=user.headers, json={"platform": platform, "token": token, "app_version": version})


def latest(db, user: AuthedUser) -> Notification:
    return db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.created_at.desc()).first()


def test_register_refresh_and_remove_devices(client: TestClient, db, maya, leo) -> None:
    first = register(client, maya, "tok-1")
    assert first.status_code == 200, first.text
    assert first.json()["platform"] == "ios" and first.json()["app_version"] == "1.0"
    refreshed = register(client, maya, "tok-1", version="1.1").json()
    assert refreshed["app_version"] == "1.1" and refreshed["created_at"] == first.json()["created_at"]

    register(client, leo, "tok-1", platform="android")
    device = db.query(DeviceToken).one()
    assert (device.user_id, device.platform) == (leo.id, "android")

    assert client.delete(f"{DEVICES_URL}/tok-1", headers=maya.headers).status_code == 204
    assert db.query(DeviceToken).count() == 1
    assert client.delete(f"{DEVICES_URL}/tok-1", headers=leo.headers).status_code == 204
    assert db.query(DeviceToken).count() == 0
    assert register(client, maya, "x", platform="windows").status_code == 422
    assert client.post(DEVICES_URL, json={"platform": "ios", "token": "t"}).status_code == 401


def test_push_goes_to_every_device_with_badge_and_collapse_key(client: TestClient, db, maya, leo) -> None:
    register(client, maya, "ios-token")
    register(client, maya, "android-token", platform="android")
    follow(client, maya, leo)
    chat = client.post("/api/v1/conversations", headers=leo.headers, json={"type": "direct", "member_ids": [str(maya.id)]}).json()["id"]
    client.post(f"/api/v1/conversations/{chat}/messages", headers=leo.headers, json={"kind": "text", "body": "hey"})
    follow(client, leo, maya)
    sender = FakeSender()

    sent = notification_service.deliver_push(db, latest(db, maya).id, sender)

    assert sent == 2
    by_platform = {m.platform: m for m in sender.sent}
    assert by_platform["ios"].badge == 3
    assert by_platform["android"].badge is None
    assert by_platform["ios"].title == "New follower" and by_platform["ios"].body == "Leo started following you"
    assert by_platform["ios"].collapse_key == latest(db, maya).group_key
    assert by_platform["ios"].data["link"] == "/users/leo"


def test_invalid_tokens_are_removed(client: TestClient, db, maya, leo) -> None:
    register(client, maya, "good")
    register(client, maya, "stale")
    follow(client, leo, maya)

    sent = notification_service.deliver_push(db, latest(db, maya).id, FakeSender(invalid={"stale"}))

    assert sent == 1
    assert [d.token for d in db.query(DeviceToken).all()] == ["good"]


def test_disabled_group_and_read_notifications_are_not_pushed(client: TestClient, db, maya, leo) -> None:
    register(client, maya, "tok")
    follow(client, leo, maya)
    client.patch("/api/v1/users/me/notification-settings", headers=maya.headers, json={"social": False})

    assert notification_service.deliver_push(db, latest(db, maya).id, FakeSender()) == 0

    client.patch("/api/v1/users/me/notification-settings", headers=maya.headers, json={"social": True})
    client.post("/api/v1/notifications/read", headers=maya.headers, json={"all": True})
    assert notification_service.deliver_push(db, latest(db, maya).id, FakeSender()) == 0


def test_quiet_hours_use_the_users_timezone(client: TestClient, db, maya, leo) -> None:
    register(client, maya, "tok")
    client.patch("/api/v1/users/me", headers=maya.headers, json={"timezone": "Asia/Tokyo"})
    client.patch(
        "/api/v1/users/me/notification-settings",
        headers=maya.headers,
        json={"quiet_hours_start": "22:00", "quiet_hours_end": "07:00"},
    )
    follow(client, leo, maya)
    notification_id = latest(db, maya).id

    late_night_tokyo = datetime(2026, 6, 1, 15, 0, tzinfo=UTC)
    morning_tokyo = datetime(2026, 6, 1, 23, 30, tzinfo=UTC)
    assert notification_service.deliver_push(db, notification_id, FakeSender(), now=late_night_tokyo) == 0
    assert notification_service.deliver_push(db, notification_id, FakeSender(), now=morning_tokyo) == 1


def test_quiet_hours_window() -> None:
    assert in_quiet_hours(time(22), time(7), time(23, 30))
    assert in_quiet_hours(time(22), time(7), time(6, 59))
    assert not in_quiet_hours(time(22), time(7), time(7))
    assert in_quiet_hours(time(13), time(14), time(13, 30))
    assert not in_quiet_hours(time(13), time(14), time(14, 30))
    assert not in_quiet_hours(None, None, time(3))
    assert not in_quiet_hours(time(9), time(9), time(9))


def test_unconfigured_sender_only_logs(caplog) -> None:
    get_push_sender.cache_clear()
    sender = get_push_sender()
    assert isinstance(sender, PlatformSender)
    assert all(isinstance(s, LogPushSender) for s in sender.senders.values())

    with caplog.at_level("INFO", logger="app.push"):
        result = sender.send(PushMessage(token="abcdef123456", platform="ios", title="Hi", body="There"))
    assert result is PushResult.SENT
    assert "not sent" in caplog.text
    get_push_sender.cache_clear()


def _ec_key() -> tuple[str, object]:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return pem.decode(), key.public_key()


def _apns(handler, sandbox: bool = True) -> tuple[APNsSender, object]:
    pem, public = _ec_key()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = APNsSender(key_id="KEY123", team_id="TEAM123", bundle_id="com.example.app", key_pem=pem, sandbox=sandbox, client=client)
    return sender, public


def test_apns_request_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    sender, public = _apns(handler)
    message = PushMessage(token="devtoken", platform="ios", title="T", body="B", data={"link": "/x"}, badge=4, collapse_key="like:fit:1")
    assert sender.send(message) is PushResult.SENT
    sender.send(message)

    request = seen[0]
    assert str(request.url) == "https://api.sandbox.push.apple.com/3/device/devtoken"
    assert request.headers["apns-topic"] == "com.example.app"
    assert request.headers["apns-push-type"] == "alert"
    assert request.headers["apns-collapse-id"] == "like:fit:1"
    token = request.headers["authorization"].removeprefix("bearer ")
    assert jwt.get_unverified_header(token)["kid"] == "KEY123"
    assert jwt.decode(token, public, algorithms=["ES256"])["iss"] == "TEAM123"
    assert seen[1].headers["authorization"] == request.headers["authorization"]
    body = json.loads(request.content)
    assert body == {"aps": {"alert": {"title": "T", "body": "B"}, "sound": "default", "badge": 4, "thread-id": "like:fit:1"}, "link": "/x"}


def test_apns_production_host_and_errors() -> None:
    responses = iter([
        httpx.Response(410, json={"reason": "Unregistered"}),
        httpx.Response(400, json={"reason": "BadDeviceToken"}),
        httpx.Response(429, json={"reason": "TooManyRequests"}),
    ])
    urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return next(responses)

    sender, _ = _apns(handler, sandbox=False)
    message = PushMessage(token="t", platform="ios", title="T", body="B")

    assert [sender.send(message) for _ in range(3)] == [PushResult.INVALID_TOKEN, PushResult.INVALID_TOKEN, PushResult.FAILED]
    assert urls[0].startswith("https://api.push.apple.com/")
    assert len(short_collapse_key("x" * 100)) == 64


class FakeCredentials:
    def __init__(self) -> None:
        self.valid = False
        self.token = None
        self.refreshes = 0

    def refresh(self, request) -> None:
        self.refreshes += 1
        self.valid = True
        self.token = "access-token"


def test_fcm_request_shape_and_invalid_tokens() -> None:
    seen: list[httpx.Request] = []
    responses = iter([
        httpx.Response(200, json={"name": "projects/p/messages/1"}),
        httpx.Response(404, json={"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}),
        httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT", "message": "The registration token is not a valid FCM registration token"}}),
        httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT", "message": "Invalid JSON payload"}}),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(responses)

    credentials = FakeCredentials()
    sender = FCMSender(project_id="proj", credentials=credentials, client=httpx.Client(transport=httpx.MockTransport(handler)))
    message = PushMessage(token="fcm-token", platform="android", title="T", body="B", data={"link": "/x"}, collapse_key="message:conversation:1")

    results = [sender.send(message) for _ in range(4)]

    assert results == [PushResult.SENT, PushResult.INVALID_TOKEN, PushResult.INVALID_TOKEN, PushResult.FAILED]
    assert credentials.refreshes == 1
    assert str(seen[0].url) == "https://fcm.googleapis.com/v1/projects/proj/messages:send"
    assert seen[0].headers["authorization"] == "Bearer access-token"
    body = json.loads(seen[0].content)["message"]
    assert body["token"] == "fcm-token" and body["notification"] == {"title": "T", "body": "B"}
    assert body["data"] == {"link": "/x"}
    assert body["android"]["collapse_key"] == "message:conversation:1"


def test_platform_sender_routes_by_platform() -> None:
    ios, android = FakeSender(), FakeSender()
    sender = PlatformSender(ios=ios, android=android)
    sender.send(PushMessage(token="a", platform="ios", title="", body=""))
    sender.send(PushMessage(token="b", platform="android", title="", body=""))
    assert [m.token for m in ios.sent] == ["a"] and [m.token for m in android.sent] == ["b"]


def test_scheduler_registers_jobs_without_starting() -> None:
    scheduler = create_scheduler()
    jobs = {job.id: str(job.trigger) for job in scheduler.get_jobs()}
    assert set(jobs) == {"streak_reminders", "streak_checks", "story_cleanup"}
    assert "minute='5'" in jobs["streak_reminders"] and "hour='3'" in jobs["story_cleanup"]
    assert not scheduler.running


def test_deliver_push_ignores_missing_notification(db) -> None:
    assert notification_service.deliver_push(db, uuid.uuid4(), FakeSender()) == 0
