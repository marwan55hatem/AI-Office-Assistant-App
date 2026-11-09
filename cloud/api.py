"""HTTP client for the Office Assistant API.

* The access token is kept in memory; the refresh token in Windows Credential Manager.
* A 401 triggers one token refresh and one retry; if the refresh fails the session
  is over (``SessionExpired``).
* A network error marks the client offline (``Offline``) and tells the listeners, so
  the window can show its banner; the next successful call marks it online again.
* Passwords are sent only to the sign-in endpoints and are never stored or logged.
"""
import json
import logging
import threading
from typing import Callable

import httpx

from cloud.credentials import CredentialStore

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=4.0)


class ApiError(Exception):
    """The server answered with an error. ``status`` is the HTTP status code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Offline(Exception):
    """The server could not be reached."""


class SessionExpired(Exception):
    """The sign-in is no longer valid; the user must sign in again."""


def _message(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return response.reason_phrase or "Error"
    if isinstance(detail, list):              # validation errors: first readable one
        text = detail[0].get("msg", "Invalid input") if detail else "Invalid input"
        return text.removeprefix("Value error, ")
    return str(detail or response.reason_phrase or "Error")


class ApiClient:
    def __init__(self, base_url: str, http: httpx.Client | None = None, credentials=None):
        self.base_url = base_url.rstrip("/")
        self.http = http or httpx.Client(base_url=self.base_url, timeout=TIMEOUT)
        self.credentials = credentials if credentials is not None else CredentialStore(self.base_url)
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._refresh_lock = threading.Lock()
        self._online: bool | None = None
        self._listeners: list[Callable[[bool], None]] = []
        self._expired_listeners: list[Callable[[], None]] = []
        self.me: dict | None = None

    # ------------------------------------------------------------------ state
    @property
    def online(self) -> bool:
        return bool(self._online)

    @property
    def signed_in(self) -> bool:
        return self._refresh_token is not None

    def on_connection_change(self, callback: Callable[[bool], None]) -> None:
        self._listeners.append(callback)

    def on_session_expired(self, callback: Callable[[], None]) -> None:
        self._expired_listeners.append(callback)

    def _set_online(self, online: bool) -> None:
        if online != self._online:
            self._online = online
            for callback in list(self._listeners):
                try:
                    callback(online)
                except Exception:
                    logger.warning("connection listener failed", exc_info=True)

    # ------------------------------------------------------------------ requests
    def _send(self, method: str, path: str, *, auth: bool, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        try:
            response = self.http.request(method, path, headers=headers, **kwargs)
        except httpx.TransportError:
            self._set_online(False)
            raise Offline("The server could not be reached") from None
        self._set_online(True)
        return response

    def request(self, method: str, path: str, **kwargs):
        """Call an authenticated endpoint and return the decoded JSON (or None)."""
        if not self.signed_in:
            raise SessionExpired("Not signed in")
        response = self._send(method, path, auth=True, **kwargs)
        if response.status_code == 401:
            self._refresh()
            response = self._send(method, path, auth=True, **kwargs)
            if response.status_code == 401:
                self._expire()
        if response.status_code >= 400:
            raise ApiError(response.status_code, _message(response))
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def stream_events(self, path: str, body: dict, should_stop=lambda: False):
        """POST and yield the server-sent events of a streamed answer as dicts.

        Stops reading (and closes the connection, which also stops the server) as soon
        as ``should_stop()`` is true.
        """
        if not self.signed_in:
            raise SessionExpired("Not signed in")
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._access_token}", "Accept": "text/event-stream"}
            try:
                with self.http.stream("POST", path, json=body, headers=headers,
                                      timeout=httpx.Timeout(120.0, connect=4.0)) as response:
                    self._set_online(True)
                    if response.status_code == 401 and attempt == 1:
                        response.read()
                        self._refresh()
                        continue
                    if response.status_code == 401:
                        self._expire()
                    if response.status_code >= 400:
                        response.read()
                        raise ApiError(response.status_code, _message(response))
                    for line in response.iter_lines():
                        if should_stop():
                            return
                        if line.startswith("data: "):
                            yield json.loads(line[6:])
                    return
            except httpx.TransportError:
                self._set_online(False)
                raise Offline("The server could not be reached") from None

    def get(self, path, **params):
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path, body=None):
        return self.request("POST", path, json=body)

    def put(self, path, body=None):
        return self.request("PUT", path, json=body)

    def patch(self, path, body=None):
        return self.request("PATCH", path, json=body)

    def delete(self, path):
        return self.request("DELETE", path)

    # ------------------------------------------------------------------ tokens
    def _store_tokens(self, pair: dict, remember: bool = True) -> None:
        self._access_token = pair["access_token"]
        self._refresh_token = pair["refresh_token"]
        if remember:
            self.credentials.save(self._refresh_token)

    def _refresh(self) -> None:
        with self._refresh_lock:
            token = self._refresh_token
            if token is None:
                self._expire()
            response = self._send("POST", "/auth/refresh", auth=False, json={"refresh_token": token})
            if response.status_code != 200:
                self._expire()
            self._store_tokens(response.json(), remember=self.credentials.load() is not None)

    def _expire(self):
        self._access_token = self._refresh_token = None
        self.credentials.delete()
        for callback in list(self._expired_listeners):
            try:
                callback()
            except Exception:
                logger.warning("session-expired listener failed", exc_info=True)
        raise SessionExpired("Please sign in again")

    # ------------------------------------------------------------------ account flows
    def login(self, email: str, password: str, remember: bool = True) -> dict:
        response = self._send("POST", "/auth/login", auth=False, json={"email": email, "password": password})
        if response.status_code != 200:
            raise ApiError(response.status_code, _message(response))
        self._store_tokens(response.json(), remember)
        return self.load_me()

    def restore(self) -> dict | None:
        """Sign in again with the remembered refresh token; None if there is none or it is invalid."""
        token = self.credentials.load()
        if not token:
            return None
        self._refresh_token = token
        try:
            self._refresh()
            return self.load_me()
        except SessionExpired:
            return None

    def load_me(self) -> dict:
        self.me = self.request("GET", "/auth/me")
        return self.me

    def logout(self) -> None:
        token = self._refresh_token
        self._access_token = self._refresh_token = None
        self.me = None
        self.credentials.delete()
        if token:
            try:
                self._send("POST", "/auth/logout", auth=False, json={"refresh_token": token})
            except Offline:
                pass                         # the token still expires on its own

    def join(self, full_name: str, email: str, password: str, company_code=None, invite_token=None) -> str:
        body = {"full_name": full_name, "email": email, "password": password}
        if invite_token:
            body["invite_token"] = invite_token
        else:
            body["company_code"] = company_code
        response = self._send("POST", "/auth/join", auth=False, json=body)
        if response.status_code != 201:
            raise ApiError(response.status_code, _message(response))
        return response.json()["message"]

    def change_password(self, current: str, new: str) -> None:
        pair = self.request("POST", "/auth/change-password", json={"current_password": current, "new_password": new})
        self._store_tokens(pair, remember=self.credentials.load() is not None)

    def close(self) -> None:
        self.http.close()
