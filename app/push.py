"""Push delivery behind a small interface: APNs (token auth, HTTP/2), FCM HTTP v1, or a logger.

`get_push_sender()` routes iOS tokens to APNs and Android tokens to FCM when they're configured,
and logs the rest. `push_queue` runs deliveries on worker threads so API requests never wait on
Apple or Google. The queue is in-process: pushes still waiting when the process stops are dropped.
"""

import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx
import jwt
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from app.core.config import settings

logger = logging.getLogger(__name__)

APNS_TOKEN_LIFETIME = 50 * 60
APNS_INVALID_REASONS = {"BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered", "ExpiredToken"}
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


@dataclass(frozen=True)
class PushMessage:
    token: str
    platform: str
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)
    badge: int | None = None
    collapse_key: str | None = None


class PushResult(Enum):
    SENT = "sent"
    INVALID_TOKEN = "invalid_token"
    FAILED = "failed"


class PushSender(Protocol):
    def send(self, message: PushMessage) -> PushResult: ...


def short_collapse_key(key: str) -> str:
    """APNs allows 64 bytes; long group keys are hashed to fit."""
    return key if len(key.encode()) <= 64 else hashlib.sha256(key.encode()).hexdigest()


class LogPushSender:
    """Used when no provider is configured: records what would have been sent."""

    def send(self, message: PushMessage) -> PushResult:
        logger.info(
            "push (not sent, no provider): platform=%s token=%s... title=%r body=%r badge=%s collapse=%s",
            message.platform,
            message.token[:8],
            message.title,
            message.body,
            message.badge,
            message.collapse_key,
        )
        return PushResult.SENT


class APNsSender:
    def __init__(
        self, *, key_id: str, team_id: str, bundle_id: str, key_pem: str, sandbox: bool, client: httpx.Client | None = None
    ) -> None:
        self.key_id = key_id
        self.team_id = team_id
        self.bundle_id = bundle_id
        self.key_pem = key_pem
        host = "api.sandbox.push.apple.com" if sandbox else "api.push.apple.com"
        self.base_url = f"https://{host}"
        self.client = client or httpx.Client(http2=True, timeout=10)
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    def _provider_token(self) -> str:
        with self._lock:
            now = time.time()
            if self._token is None or now - self._token[1] > APNS_TOKEN_LIFETIME:
                signed = jwt.encode(
                    {"iss": self.team_id, "iat": int(now)}, self.key_pem, algorithm="ES256", headers={"kid": self.key_id}
                )
                self._token = (signed, now)
            return self._token[0]

    def _payload(self, message: PushMessage) -> dict:
        aps: dict = {"alert": {"title": message.title, "body": message.body}, "sound": "default"}
        if message.badge is not None:
            aps["badge"] = message.badge
        if message.collapse_key:
            aps["thread-id"] = message.collapse_key
        return {"aps": aps, **message.data}

    def send(self, message: PushMessage) -> PushResult:
        headers = {
            "authorization": f"bearer {self._provider_token()}",
            "apns-topic": self.bundle_id,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        if message.collapse_key:
            headers["apns-collapse-id"] = short_collapse_key(message.collapse_key)
        try:
            response = self.client.post(
                f"{self.base_url}/3/device/{message.token}", json=self._payload(message), headers=headers
            )
        except httpx.HTTPError:
            logger.exception("APNs request failed")
            return PushResult.FAILED
        if response.status_code == 200:
            return PushResult.SENT
        reason = _json(response).get("reason", "")
        if response.status_code == 410 or reason in APNS_INVALID_REASONS:
            return PushResult.INVALID_TOKEN
        logger.warning("APNs rejected a push: %s %s", response.status_code, reason)
        return PushResult.FAILED


class FCMSender:
    def __init__(self, *, project_id: str, credentials, client: httpx.Client | None = None) -> None:
        self.url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        self.credentials = credentials
        self.client = client or httpx.Client(timeout=10)
        self._lock = threading.Lock()

    def _access_token(self) -> str:
        with self._lock:
            if not self.credentials.valid:
                self.credentials.refresh(Request())
            return self.credentials.token

    def _body(self, message: PushMessage) -> dict:
        android: dict = {"priority": "high"}
        if message.collapse_key:
            android["collapse_key"] = message.collapse_key
            android["notification"] = {"tag": message.collapse_key}
        return {
            "message": {
                "token": message.token,
                "notification": {"title": message.title, "body": message.body},
                "data": message.data,
                "android": android,
            }
        }

    def send(self, message: PushMessage) -> PushResult:
        try:
            response = self.client.post(
                self.url, json=self._body(message), headers={"Authorization": f"Bearer {self._access_token()}"}
            )
        except Exception:
            logger.exception("FCM request failed")
            return PushResult.FAILED
        if response.status_code == 200:
            return PushResult.SENT
        if _fcm_token_invalid(response):
            return PushResult.INVALID_TOKEN
        logger.warning("FCM rejected a push: %s %s", response.status_code, response.text[:200])
        return PushResult.FAILED


def _json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _fcm_token_invalid(response: httpx.Response) -> bool:
    error = _json(response).get("error") or {}
    codes = {d.get("errorCode") for d in error.get("details", []) if isinstance(d, dict)}
    codes.add(error.get("status"))
    if codes & {"UNREGISTERED", "NOT_FOUND"}:
        return True
    return "INVALID_ARGUMENT" in codes and "token" in str(error.get("message", "")).lower()


class PlatformSender:
    """Sends each message with the sender for its platform."""

    def __init__(self, ios: PushSender, android: PushSender) -> None:
        self.senders = {"ios": ios, "android": android}

    def send(self, message: PushMessage) -> PushResult:
        return self.senders[message.platform].send(message)


def _apns_sender() -> PushSender | None:
    if not settings.apns_configured:
        return None
    return APNsSender(
        key_id=settings.APNS_KEY_ID,
        team_id=settings.APNS_TEAM_ID,
        bundle_id=settings.APNS_BUNDLE_ID,
        key_pem=Path(settings.APNS_KEY_PATH).read_text(),
        sandbox=settings.APNS_USE_SANDBOX,
    )


def _fcm_sender() -> PushSender | None:
    if not settings.fcm_configured:
        return None
    credentials = service_account.Credentials.from_service_account_file(
        settings.FCM_CREDENTIALS_PATH, scopes=[FCM_SCOPE]
    )
    return FCMSender(project_id=settings.FCM_PROJECT_ID, credentials=credentials)


@lru_cache
def get_push_sender() -> PushSender:
    log = LogPushSender()
    fcm = _fcm_sender()
    return PlatformSender(ios=_apns_sender() or log, android=fcm or log)


class PushQueue:
    """Runs push deliveries on background threads."""

    def __init__(self, workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="push")

    def submit(self, fn, *args) -> None:
        self._executor.submit(self._run, fn, *args)

    @staticmethod
    def _run(fn, *args) -> None:
        try:
            fn(*args)
        except Exception:
            logger.exception("push delivery failed")


push_queue = PushQueue()
