"""S3-compatible storage (Cloudflare R2, AWS S3): request signing and the save / read / delete
calls, against a fake bucket."""

import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.storage import S3Storage, StorageError, sign_v4

EMPTY_HASH = hashlib.sha256(b"").hexdigest()


def test_signature_matches_the_aws_documentation_example() -> None:
    # "Example: GET Object" from AWS's Signature Version 4 docs for S3.
    authorization = sign_v4(
        method="GET",
        host="examplebucket.s3.amazonaws.com",
        path="/test.txt",
        headers={
            "range": "bytes=0-9",
            "x-amz-content-sha256": EMPTY_HASH,
            "x-amz-date": "20130524T000000Z",
        },
        payload_hash=EMPTY_HASH,
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        now=datetime(2013, 5, 24, tzinfo=UTC),
    )

    assert authorization == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


class FakeBucket:
    """Answers S3 requests from a dict, and records them."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = request.url.path.removeprefix("/media-bucket/")
        if request.method == "PUT":
            self.objects[key] = request.content
            return httpx.Response(200)
        if request.method == "GET":
            return httpx.Response(200, content=self.objects[key]) if key in self.objects else httpx.Response(404)
        if request.method == "DELETE":
            self.objects.pop(key, None)
            return httpx.Response(204)
        return httpx.Response(405)


@pytest.fixture
def bucket() -> FakeBucket:
    return FakeBucket()


@pytest.fixture
def storage(bucket: FakeBucket) -> S3Storage:
    return S3Storage(
        endpoint="https://account.r2.cloudflarestorage.com/",
        bucket="media-bucket",
        access_key="key-id",
        secret_key="secret",
        client=httpx.Client(transport=httpx.MockTransport(bucket)),
    )


def test_save_read_and_delete(storage: S3Storage, bucket: FakeBucket) -> None:
    storage.save("images/abc.webp", b"webp-bytes", "image/webp")

    put = bucket.requests[0]
    assert put.method == "PUT"
    assert str(put.url) == "https://account.r2.cloudflarestorage.com/media-bucket/images/abc.webp"
    assert put.headers["content-type"] == "image/webp"
    assert "immutable" in put.headers["cache-control"]
    assert put.headers["x-amz-content-sha256"] == hashlib.sha256(b"webp-bytes").hexdigest()
    assert put.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=key-id/")
    assert "/auto/s3/aws4_request" in put.headers["authorization"]

    assert storage.read("images/abc.webp") == b"webp-bytes"

    storage.delete("images/abc.webp")
    assert bucket.objects == {}
    # Already gone: no error, like local storage.
    storage.delete("images/abc.webp")


def test_reading_a_missing_file_raises_file_not_found(storage: S3Storage) -> None:
    with pytest.raises(FileNotFoundError):
        storage.read("images/missing.webp")


def test_a_refused_upload_raises(bucket: FakeBucket) -> None:
    storage = S3Storage(
        endpoint="https://account.r2.cloudflarestorage.com",
        bucket="media-bucket",
        access_key="wrong",
        secret_key="wrong",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403))),
    )

    with pytest.raises(StorageError):
        storage.save("images/abc.webp", b"x", "image/webp")


def test_s3_storage_needs_its_bucket_settings() -> None:
    with pytest.raises(ValidationError, match="S3_BUCKET"):
        Settings(
            _env_file=None,  # only the values below, not the developer's .env
            STORAGE_BACKEND="s3",
            S3_ENDPOINT_URL="https://account.r2.cloudflarestorage.com",
            S3_ACCESS_KEY_ID="key-id",
            S3_SECRET_ACCESS_KEY="secret",
        )
