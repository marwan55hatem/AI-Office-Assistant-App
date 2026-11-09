"""Live delivery for the manager-employee chat: who is connected, and pushing events to them.

Connections are kept in memory per ``(company, user)``, so this works for **one** server
process. Several instances would need a shared channel (e.g. PostgreSQL LISTEN/NOTIFY or
Redis pub/sub) behind :meth:`ChatHub.publish`; the REST API stays the source of truth either
way, and clients that miss a push catch up over HTTP.

The request handlers are synchronous (they run in worker threads), so :meth:`publish`
hands the event to the event loop the WebSockets live on.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections import defaultdict

logger = logging.getLogger("office.chat")


class ChatHub:
    def __init__(self):
        self._sockets: dict[tuple, set] = defaultdict(set)
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- connections ----------------------------------------------------------
    def add(self, company_id: uuid.UUID, user_id: uuid.UUID, socket) -> None:
        self._loop = asyncio.get_running_loop()
        with self._lock:
            self._sockets[(str(company_id), str(user_id))].add(socket)

    def remove(self, company_id: uuid.UUID, user_id: uuid.UUID, socket) -> None:
        key = (str(company_id), str(user_id))
        with self._lock:
            self._sockets[key].discard(socket)
            if not self._sockets[key]:
                del self._sockets[key]

    def is_online(self, company_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        with self._lock:
            return bool(self._sockets.get((str(company_id), str(user_id))))

    def connections(self) -> int:
        with self._lock:
            return sum(len(s) for s in self._sockets.values())

    def clear(self) -> None:
        with self._lock:
            self._sockets.clear()

    # -- pushing ----------------------------------------------------------------
    def publish(self, company_id: uuid.UUID, user_ids, event: dict) -> None:
        """Send ``event`` to every open connection of these users (from any thread)."""
        with self._lock:
            targets = [s for uid in {str(u) for u in user_ids}
                       for s in self._sockets.get((str(company_id), uid), ())]
        if not targets or self._loop is None or self._loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            running.create_task(self._send(targets, event))
        else:
            asyncio.run_coroutine_threadsafe(self._send(targets, event), self._loop)

    async def _send(self, targets, event: dict) -> None:
        for socket in targets:
            try:
                await socket.send_json(event)
            except Exception:                      # a closed socket; its handler removes it
                logger.debug("push to a closed socket skipped")


hub = ChatHub()
