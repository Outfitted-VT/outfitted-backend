"""In-process WebSocket hub for messaging events.

Keeps the open sockets of each user and pushes JSON events to them. Endpoints run in a worker
thread, so `publish` hands the sends to the event loop the sockets live on. One hub per process:
running several workers needs a shared broker (e.g. Redis pub/sub) in front of this.
"""

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Iterable

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder


class Hub:
    def __init__(self) -> None:
        self._sockets: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def add(self, user_id: uuid.UUID, socket: WebSocket) -> bool:
        """Register a socket. True when this is the user's first open socket."""
        self._loop = asyncio.get_running_loop()
        first = not self._sockets[user_id]
        self._sockets[user_id].add(socket)
        return first

    def remove(self, user_id: uuid.UUID, socket: WebSocket) -> bool:
        """Forget a socket. True when the user has no open sockets left."""
        sockets = self._sockets.get(user_id)
        if sockets is None:
            return False
        sockets.discard(socket)
        if sockets:
            return False
        del self._sockets[user_id]
        return True

    def is_online(self, user_id: uuid.UUID) -> bool:
        return bool(self._sockets.get(user_id))

    def publish(self, user_ids: Iterable[uuid.UUID], event: dict) -> None:
        """Send an event to every open socket of the given users. Safe from any thread."""
        if self._loop is None or self._loop.is_closed():
            return
        message = jsonable_encoder(event)
        targets = [s for user_id in set(user_ids) for s in self._sockets.get(user_id, ())]
        if not targets:
            return
        coroutine = self._send_all(targets, message)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._loop.create_task(coroutine)
        else:
            asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    async def _send_all(self, sockets: list[WebSocket], message: dict) -> None:
        await asyncio.gather(*(self._send(s, message) for s in sockets))

    @staticmethod
    async def _send(socket: WebSocket, message: dict) -> None:
        try:
            await socket.send_json(message)
        except Exception:
            pass


hub = Hub()
