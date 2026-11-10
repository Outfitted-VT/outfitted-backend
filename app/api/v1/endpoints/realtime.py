"""WebSocket for messaging events.

Connect to `/api/v1/ws`, then send `{"type": "auth", "token": "<access token>"}` as the first
message within 10 seconds (tokens stay out of URLs and logs). The server answers
`{"type": "ready"}` and then pushes events. Clients may send `typing:start`, `typing:stop`
(with `conversation_id`) and `ping`.
"""

import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import SessionDep
from app.core.security import decode_access_token
from app.models.user import User
from app.realtime import hub
from app.services import conversation as service
from app.services.user import get_user

router = APIRouter()

AUTH_TIMEOUT_SECONDS = 10
UNAUTHORIZED = 4401
TYPING_EVENTS = {"typing:start", "typing:stop"}


async def _run(db: Session, fn, *args):
    """Run a database call off the event loop, then end its transaction so an idle socket holds no connection."""
    try:
        result = await run_in_threadpool(fn, db, *args)
    except Exception:
        await run_in_threadpool(db.rollback)
        raise
    await run_in_threadpool(db.commit)
    return result


async def _authenticate(socket: WebSocket, db) -> User | None:
    try:
        first = await asyncio.wait_for(socket.receive_json(), AUTH_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
        return None
    if not isinstance(first, dict) or first.get("type") != "auth":
        return None
    user_id = decode_access_token(str(first.get("token", "")))
    if user_id is None:
        return None
    user = await _run(db, get_user, user_id)
    return user if user is not None and user.is_active else None


def _parse(text: str) -> dict | None:
    try:
        event = json.loads(text)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def _conversation_id(event: dict) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(event.get("conversation_id")))
    except ValueError:
        return None


async def _handle(socket: WebSocket, db, user: User, event: dict, members: set[uuid.UUID]) -> None:
    kind = event.get("type")
    if kind == "ping":
        await socket.send_json({"type": "pong"})
        return
    if kind not in TYPING_EVENTS:
        return
    conversation_id = _conversation_id(event)
    if conversation_id is None:
        return
    if conversation_id not in members:
        if not await _run(db, service.is_member, user.id, conversation_id):
            return
        members.add(conversation_id)
    await _run(db, service.publish_typing, user, conversation_id, kind)


@router.websocket("")
async def messaging_socket(socket: WebSocket, db: SessionDep) -> None:
    await socket.accept()
    user = await _authenticate(socket, db)
    if user is None:
        await socket.close(code=UNAUTHORIZED)
        return

    if hub.add(user.id, socket):
        await _run(db, service.touch_presence, user, True)
    await socket.send_json({"type": "ready", "user_id": str(user.id)})
    members: set[uuid.UUID] = set()
    try:
        while True:
            event = _parse(await socket.receive_text())
            if event is not None:
                await _handle(socket, db, user, event, members)
    except WebSocketDisconnect:
        pass
    finally:
        if hub.remove(user.id, socket):
            await _run(db, service.touch_presence, user, False)
