"""File storage behind a small interface, so local disk can be swapped for S3/R2 later."""

from functools import lru_cache
from pathlib import Path
from typing import Protocol

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


@lru_cache
def get_storage() -> Storage:
    return LocalStorage(Path(settings.MEDIA_ROOT))


def media_url(key: str) -> str:
    return f"{settings.MEDIA_BASE_URL.rstrip('/')}/{key}"
