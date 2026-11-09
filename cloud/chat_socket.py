"""The live chat channel (``/chat/ws``) for the desktop app, on Qt's own WebSocket.

It only *receives* events (``message``, ``read``, ``delivered``, ``typing``) and sends
typing hints; messages are sent and fetched over HTTP, so nothing is lost while the
socket is down -- the Messages page catches up with ``after_id`` and polls meanwhile.

* The access token is sent as the first message, never in the URL.
* The server closes the socket when the token expires (4001): reconnect at once with a
  fresh token. A refused token (4003) gets one retry with a refreshed token.
* Any other drop reconnects after 2, 5, 10, 30, 30 ... seconds. A ping every 25 s keeps
  proxies from closing an idle connection.
"""
import json
import logging

from PyQt5.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt5.QtWebSockets import QWebSocket

logger = logging.getLogger(__name__)

BACKOFF_MS = (2000, 5000, 10000, 30000)
PING_MS = 25000


class ChatSocket(QObject):
    event_received = pyqtSignal(dict)
    connected_changed = pyqtSignal(bool)

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.connected = False
        self._wanted = False
        self._failures = 0
        self._auth_retry = False
        self.socket = QWebSocket()
        self.socket.connected.connect(self._on_open)
        self.socket.disconnected.connect(self._on_closed)
        self.socket.textMessageReceived.connect(self._on_text)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._open)
        self._ping = QTimer(self)
        self._ping.setInterval(PING_MS)
        self._ping.timeout.connect(lambda: self.send({"type": "ping"}))

    # ------------------------------------------------------------------ control
    def start(self):
        self._wanted = True
        self._open()

    def stop(self):
        self._wanted = False
        self._retry.stop()
        self._ping.stop()
        self.socket.abort()
        self._set_connected(False)

    def send(self, event: dict) -> bool:
        if not self.connected:
            return False
        self.socket.sendTextMessage(json.dumps(event))
        return True

    def typing(self, employee_id) -> bool:
        return self.send({"type": "typing", "employee_id": str(employee_id)})

    # ------------------------------------------------------------------ internals
    def _open(self):
        if not self._wanted or not self.api.signed_in:
            return
        self.socket.abort()
        self.socket.open(QUrl(self.api.socket_url("/chat/ws")))

    def _on_open(self):
        try:
            token = self.api.socket_token(force=self._auth_retry)
        except Exception:                           # offline or signed out: try again later
            logger.info("chat: no token for the live channel")
            self.socket.abort()
            return
        self.socket.sendTextMessage(json.dumps({"type": "auth", "token": token}))

    def _on_text(self, text):
        try:
            event = json.loads(text)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        if event.get("type") == "ready":
            self._failures = 0
            self._auth_retry = False
            self._ping.start()
            self._set_connected(True)
            return
        if event.get("type") in ("pong", "expired"):
            return
        self.event_received.emit(event)

    def _on_closed(self):
        self._ping.stop()
        code = int(self.socket.closeCode())
        self._set_connected(False)
        if not self._wanted:
            return
        if code == 4001:                            # token expired: a fresh one at once
            self._retry.start(0)
            return
        if code == 4003 and not self._auth_retry:   # refused: refresh the token once
            self._auth_retry = True
            self._retry.start(0)
            return
        delay = BACKOFF_MS[min(self._failures, len(BACKOFF_MS) - 1)]
        self._failures += 1
        self._retry.start(delay)

    def _set_connected(self, value):
        if value != self.connected:
            self.connected = value
            self.connected_changed.emit(value)
