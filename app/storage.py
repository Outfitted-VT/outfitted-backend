"""File storage behind a small interface: local disk in development, an S3-compatible bucket
(Cloudflare R2, AWS S3, ...) when hosted, chosen by STORAGE_BACKEND."""

import hashlib
import hmac
import ssl
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import settings


class Storage(Protocol):
    def save(self, key: str, data: bytes, content_type: str) -> None: ...

    def read(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Stores files under a directory on disk; main.py serves it at /media."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok=True)


class StorageError(Exception):
    """The bucket refused a request (wrong keys, missing bucket, ...)."""


# Keys name new files (e.g. images/<uuid>.webp) and never change, so clients may cache forever.
CACHE_CONTROL = "public, max-age=31536000, immutable"


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def sign_v4(
    *,
    method: str,
    host: str,
    path: str,
    headers: dict[str, str],
    payload_hash: str,
    access_key: str,
    secret_key: str,
    region: str,
    now: datetime,
) -> str:
    """The Authorization header for an S3 request (AWS Signature Version 4, no query string).
    `path` is already URI-encoded; every header in `headers` (lowercase names) is signed, plus
    host."""
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    signed = {**headers, "host": host}
    names = sorted(signed)
    canonical_headers = "".join(f"{name}:{signed[name].strip()}\n" for name in names)
    signed_headers = ";".join(names)
    canonical_request = "\n".join([method, path, "", canonical_headers, signed_headers, payload_hash])
    scope = f"{day}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    key = _hmac(f"AWS4{secret_key}".encode(), day)
    for part in (region, "s3", "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


class S3Storage:
    """Stores files in an S3-compatible bucket. Requests are signed with AWS Signature V4 and
    sent with httpx, so no AWS SDK is needed. Path-style URLs: {endpoint}/{bucket}/{key}.

    For Cloudflare R2 the endpoint is https://<account id>.r2.cloudflarestorage.com and the
    region "auto". Clients load the files from MEDIA_BASE_URL (the bucket's public URL)."""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "auto",
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        # The operating system's certificate store (not httpx's bundled list), so HTTPS works
        # behind antivirus or a company proxy that the OS trusts.
        self.client = client or httpx.Client(timeout=30, verify=ssl.create_default_context())

    def _request(
        self, method: str, key: str, body: bytes = b"", headers: dict[str, str] | None = None
    ) -> httpx.Response:
        url = f"{self.endpoint}/{quote(self.bucket)}/{quote(key, safe='/-_.~')}"
        parts = urlsplit(url)
        payload_hash = hashlib.sha256(body).hexdigest()
        now = datetime.now(UTC)
        signed = {
            **{name.lower(): value for name, value in (headers or {}).items()},
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": now.strftime("%Y%m%dT%H%M%SZ"),
        }
        authorization = sign_v4(
            method=method,
            host=parts.netloc,
            path=parts.path,
            headers=signed,
            payload_hash=payload_hash,
            access_key=self.access_key,
            secret_key=self.secret_key,
            region=self.region,
            now=now,
        )
        return self.client.request(
            method, url, content=body or None, headers={**signed, "authorization": authorization}
        )

    def save(self, key: str, data: bytes, content_type: str) -> None:
        response = self._request(
            "PUT", key, data, {"content-type": content_type, "cache-control": CACHE_CONTROL}
        )
        if response.status_code >= 300:
            raise StorageError(f"Couldn't upload {key}: HTTP {response.status_code}")

    def read(self, key: str) -> bytes:
        response = self._request("GET", key)
        if response.status_code == 404:
            raise FileNotFoundError(key)  # like LocalStorage
        if response.status_code >= 300:
            raise StorageError(f"Couldn't read {key}: HTTP {response.status_code}")
        return response.content

    def delete(self, key: str) -> None:
        response = self._request("DELETE", key)
        # Deleting something already gone is fine, as with LocalStorage.
        if response.status_code >= 300 and response.status_code != 404:
            raise StorageError(f"Couldn't delete {key}: HTTP {response.status_code}")


@lru_cache
def get_storage() -> Storage:
    if settings.STORAGE_BACKEND == "s3":
        return S3Storage(
            endpoint=settings.S3_ENDPOINT_URL,
            bucket=settings.S3_BUCKET,
            access_key=settings.S3_ACCESS_KEY_ID,
            secret_key=settings.S3_SECRET_ACCESS_KEY,
            region=settings.S3_REGION,
        )
    return LocalStorage(Path(settings.MEDIA_ROOT))


def media_url(key: str) -> str:
    return f"{settings.MEDIA_BASE_URL.rstrip('/')}/{key}"
