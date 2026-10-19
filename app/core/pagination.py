"""Cursor pagination for newest-first lists.

A cursor encodes the (created_at, id) of the last item on a page. The next page continues
strictly after it, so items added while someone scrolls don't cause skips or duplicates
(unlike offset pagination). Cursors are opaque to clients.
"""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime


class InvalidCursorError(Exception):
    pass


@dataclass(frozen=True)
class Cursor:
    created_at: datetime
    id: uuid.UUID


def encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    payload = json.dumps([created_at.isoformat(), str(item_id)])
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Cursor:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created_at, item_id = json.loads(base64.urlsafe_b64decode(padded))
        return Cursor(created_at=datetime.fromisoformat(created_at), id=uuid.UUID(item_id))
    except (ValueError, TypeError):
        raise InvalidCursorError from None
