"""A local fake of Slack: its Web API (the methods Themi calls), Socket Mode, and files.

    async def test_a_dm(fake_slack, channel):
        await channel.dispatch(fake_slack.dm(MICHAEL, "hello"))
        assert fake_slack.texts(MICHAEL) == ["Hi Michael! ..."]

Envelopes (what Socket Mode delivers) are made by `dm`, `tap`, `react` and `slash`, and
either handed to the channel's dispatcher directly or queued for the socket with `push`.
Tokens are checked per method (bot, app-level, user), so a client using the wrong one
gets Slack's `invalid_auth`. Errors can be queued per method with `fail`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import queue
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import count
from typing import Any

import pytest
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from tests.fakes._server import BackgroundServer

BOT_TOKEN = "xoxb-fake-bot-token-for-the-local-test-server"
APP_TOKEN = "xapp-fake-app-level-token-for-the-local-test-server"
USER_TOKEN = "xoxp-fake-user-token-for-the-local-test-server"
BOT_USER = "UTHEMI"
TEAM = "TWORK"
MICHAEL = "UMICHAEL"
STRANGER = "USTRANGER"
USERS = {
    MICHAEL: ("Michael", "michael@work.test"),
    STRANGER: ("Someone Else", "someone@work.test"),
}
APP_METHODS = {"apps.connections.open"}
USER_METHODS = {"users.profile.set", "dnd.setSnooze", "dnd.endSnooze"}


@dataclass
class ApiCall:
    method: str
    params: dict[str, Any]
    ok: bool = True  # False: Slack said no (a queued failure, the wrong token)


@dataclass
class _Failure:
    error: str
    status: int
    retry_after: int | None


@dataclass
class FakeSlackState:
    calls: list[ApiCall] = field(default_factory=list)
    failures: dict[str, list[_Failure]] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)
    uploads: dict[str, bytes] = field(default_factory=dict)
    users: dict[str, tuple[str, str]] = field(default_factory=lambda: dict(USERS))
    acks: list[dict[str, Any]] = field(default_factory=list)
    connections: int = 0


class FakeSlack:
    def __init__(self, port: int = 0) -> None:
        self.state = FakeSlackState()
        self._lock = threading.Lock()
        self._ts = count(1)
        self._ids = count(1)
        self._outgoing: queue.Queue[dict[str, Any] | str] = queue.Queue()
        self.app = FastAPI()
        self.app.add_api_route("/api/{method}", self._api, methods=["POST"])
        self.app.add_api_route("/files/{file_id}", self._file, methods=["GET"])
        self.app.add_api_route("/upload/{file_id}", self._upload, methods=["POST"])
        self.app.add_api_websocket_route("/link", self._socket)
        self._background = BackgroundServer(self.app, port)

    # ----- wiring -----------------------------------------------------------------------

    @property
    def url(self) -> str:
        return self._background.url

    @property
    def base_url(self) -> str:
        return f"{self.url}/api"

    def start(self) -> None:
        self._background.start()

    def stop(self) -> None:
        self._background.stop()

    def reset(self) -> None:
        with self._lock:
            self.state = FakeSlackState()
        while not self._outgoing.empty():
            self._outgoing.get_nowait()

    # ----- making what Slack would send ---------------------------------------------------

    def next_ts(self) -> str:
        n = next(self._ts)
        return f"{1_790_000_000 + n}.{n:06d}"

    @staticmethod
    def dm_channel(user: str) -> str:
        return f"D{user[1:]}"

    def _envelope(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        n = next(self._ids)
        return {
            "envelope_id": f"env-{n}",
            "type": kind,
            "payload": payload,
            "accepts_response_payload": False,
        }

    def event(self, event: dict[str, Any], *, event_id: str | None = None) -> dict[str, Any]:
        n = next(self._ids)
        payload = {
            "team_id": TEAM,
            "type": "event_callback",
            "event_id": event_id or f"Ev{n:06d}",
            "event_time": 1_790_000_000 + n,
            "event": event,
        }
        return self._envelope("events_api", payload)

    def dm(
        self,
        user: str,
        text: str,
        *,
        thread_ts: str | None = None,
        files: list[dict[str, Any]] | None = None,
        subtype: str | None = None,
        ts: str | None = None,
    ) -> dict[str, Any]:
        """A message in the user's DM with Themi, as a Socket Mode envelope."""
        event: dict[str, Any] = {
            "type": "message",
            "channel": self.dm_channel(user),
            "channel_type": "im",
            "user": user,
            "text": text,
            "ts": ts or self.next_ts(),
        }
        if thread_ts:
            event["thread_ts"] = thread_ts
        if files:
            event["files"] = files
            event["subtype"] = "file_share"
        if subtype:
            event["subtype"] = subtype
        return self.event(event)

    def add_file(
        self, data: bytes, mimetype: str, name: str = "file", **extra: Any
    ) -> dict[str, Any]:
        n = next(self._ids)
        file_id = f"F{n:06d}"
        with self._lock:
            self.state.files[file_id] = data
        return {
            "id": file_id,
            "name": name,
            "mimetype": mimetype,
            "size": len(data),
            "url_private": f"{self.url}/files/{file_id}",
            "url_private_download": f"{self.url}/files/{file_id}",
            **extra,
        }

    def tap(
        self, user: str, value: str, message_ts: str, *, thread_ts: str | None = None
    ) -> dict[str, Any]:
        """A tap on one of Themi's buttons."""
        channel = self.dm_channel(user)
        message: dict[str, Any] = {"ts": message_ts, "type": "message", "user": BOT_USER}
        if thread_ts:
            message["thread_ts"] = thread_ts
        payload = {
            "type": "block_actions",
            "user": {"id": user},
            "team": {"id": TEAM},
            "channel": {"id": channel},
            "container": {"type": "message", "message_ts": message_ts, "channel_id": channel},
            "message": message,
            "actions": [{"type": "button", "action_id": "themi-0", "value": value}],
            "trigger_id": "trigger",
        }
        return self._envelope("interactive", payload)

    def react(self, user: str, name: str, ts: str, *, item_user: str = BOT_USER) -> dict[str, Any]:
        return self.event(
            {
                "type": "reaction_added",
                "user": user,
                "reaction": name,
                "item_user": item_user,
                "item": {"type": "message", "channel": self.dm_channel(user), "ts": ts},
                "event_ts": self.next_ts(),
            }
        )

    def slash(self, user: str, text: str) -> dict[str, Any]:
        payload = {
            "command": "/themi",
            "text": text,
            "user_id": user,
            "channel_id": self.dm_channel(user),
            "team_id": TEAM,
            "response_url": f"{self.url}/respond",
        }
        return self._envelope("slash_commands", payload)

    # ----- the socket ---------------------------------------------------------------------

    def push(self, envelope: dict[str, Any]) -> None:
        """Send an envelope over the open socket (or the next one)."""
        self._outgoing.put(envelope)

    def disconnect(self) -> None:
        """Slack asks the client to reconnect (its `disconnect` message), then closes."""
        self._outgoing.put("disconnect")

    async def _socket(self, websocket: WebSocket) -> None:
        await websocket.accept()
        with self._lock:
            self.state.connections += 1
        await websocket.send_json({"type": "hello", "num_connections": 1})
        reader = asyncio.ensure_future(self._read_acks(websocket))
        try:
            while not reader.done():
                try:
                    item = self._outgoing.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.005)
                    continue
                if item == "disconnect":
                    # As Slack does: a warning, then time for the client to move over.
                    await websocket.send_json({"type": "disconnect", "reason": "refresh_requested"})
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(reader), timeout=2)
                    with contextlib.suppress(RuntimeError):
                        await websocket.close()
                    return
                await websocket.send_json(item)
        finally:
            reader.cancel()

    async def _read_acks(self, websocket: WebSocket) -> None:
        try:
            while True:
                ack = json.loads(await websocket.receive_text())
                with self._lock:
                    self.state.acks.append(ack)
        except (WebSocketDisconnect, RuntimeError):
            return

    def acked(self) -> list[str]:
        with self._lock:
            return [a.get("envelope_id", "") for a in self.state.acks]

    # ----- failures ------------------------------------------------------------------------

    def fail(
        self,
        method: str,
        error: str = "internal_error",
        *,
        status: int = 200,
        retry_after: int | None = None,
        times: int = 1,
    ) -> None:
        with self._lock:
            queue_ = self.state.failures.setdefault(method, [])
            queue_.extend(_Failure(error, status, retry_after) for _ in range(times))

    # ----- inspecting what Themi did ------------------------------------------------------

    def calls(self, method: str, *, failed: bool = False) -> list[dict[str, Any]]:
        """The calls Slack answered `ok` (with `failed`, every call)."""
        with self._lock:
            return [c.params for c in self.state.calls if c.method == method and (c.ok or failed)]

    def posts(self, user: str) -> list[dict[str, Any]]:
        channel = self.dm_channel(user)
        return [p for p in self.calls("chat.postMessage") if p.get("channel") == channel]

    def texts(self, user: str) -> list[str]:
        """What Themi posted in the user's DM, as the person reads it."""
        return [_shown(p) for p in self.posts(user)]

    def buttons(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            e
            for b in params.get("blocks") or []
            if b.get("type") == "actions"
            for e in b["elements"]
        ]

    def last_buttons(self, user: str) -> list[dict[str, Any]]:
        for params in reversed(self.posts(user)):
            if found := self.buttons(params):
                return found
        raise AssertionError(f"no buttons were sent to {user}")

    # ----- the HTTP side ------------------------------------------------------------------

    async def _api(self, method: str, request: Request) -> Response:
        form = await request.form()
        params: dict[str, Any] = {}
        for key, value in form.items():
            text = str(value)
            if key in ("blocks", "users", "attachments", "files", "profile") and text[:1] in "[{":
                params[key] = json.loads(text)
            else:
                params[key] = text
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        call = ApiCall(method, params)
        with self._lock:
            self.state.calls.append(call)
            pending = self.state.failures.get(method)
            failure = pending.pop(0) if pending else None
        wanted = (
            APP_TOKEN
            if method in APP_METHODS
            else USER_TOKEN
            if method in USER_METHODS
            else BOT_TOKEN
        )
        if method == "auth.test" and token in (BOT_TOKEN, USER_TOKEN):
            wanted = token
        if token != wanted or failure is not None:
            call.ok = False
        if token != wanted:
            return JSONResponse({"ok": False, "error": "invalid_auth"})
        if failure is not None:
            headers = {"Retry-After": str(failure.retry_after)} if failure.retry_after else {}
            return JSONResponse(
                {"ok": False, "error": failure.error}, status_code=failure.status, headers=headers
            )
        return JSONResponse({"ok": True, **self._result(method, params, token)})

    def _result(self, method: str, params: dict[str, Any], token: str) -> dict[str, Any]:
        if method == "auth.test":
            user = BOT_USER if token == BOT_TOKEN else MICHAEL
            return {
                "url": "https://work.slack.test/",
                "team": "Work",
                "team_id": TEAM,
                "user": "themi",
                "user_id": user,
                "bot_id": "BTHEMI",
            }
        if method == "apps.connections.open":
            return {"url": f"ws://127.0.0.1:{self._background.port}/link"}
        if method == "conversations.open":
            return {"channel": {"id": self.dm_channel(str(params["users"]))}}
        if method == "chat.postMessage":
            ts = self.next_ts()
            return {
                "channel": params["channel"],
                "ts": ts,
                "message": {"ts": ts, "text": params.get("text", ""), "user": BOT_USER},
            }
        if method == "chat.update":
            return {"channel": params["channel"], "ts": params["ts"]}
        if method == "chat.postEphemeral":
            return {"message_ts": self.next_ts()}
        if method == "users.info":
            name, email = self.state.users.get(str(params["user"]), ("", ""))
            if not name:
                return {"ok": False, "error": "user_not_found"}
            return {
                "user": {
                    "id": params["user"],
                    "name": name.lower(),
                    "real_name": name,
                    "is_bot": False,
                    "profile": {"email": email, "real_name": name},
                }
            }
        if method == "files.getUploadURLExternal":
            n = next(self._ids)
            file_id = f"F{n:06d}"
            return {"upload_url": f"{self.url}/upload/{file_id}", "file_id": file_id}
        if method == "files.completeUploadExternal":
            files = params.get("files") or []
            return {"files": [{"id": f["id"], "title": f.get("title", "")} for f in files]}
        if method == "dnd.setSnooze":
            return {"snooze_enabled": True, "snooze_endtime": 0}
        # reactions.add, users.profile.set, dnd.endSnooze ...
        return {}

    async def _file(self, file_id: str, request: Request) -> Response:
        if request.headers.get("authorization", "") != f"Bearer {BOT_TOKEN}":
            return Response(status_code=403)
        data = self.state.files.get(file_id)
        if data is None:
            return Response(status_code=404)
        return Response(content=data, media_type="application/octet-stream")

    async def _upload(self, file_id: str, request: Request) -> Response:
        form = await request.form()
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            return Response(status_code=400)
        with self._lock:
            self.state.uploads[file_id] = await upload.read()
        return Response(content=b"OK - 1", media_type="text/plain")


def _shown(params: dict[str, Any]) -> str:
    """The words of a post, unescaped (from its sections when it has blocks)."""
    blocks = params.get("blocks") or []
    words = [b["text"]["text"] for b in blocks if b.get("type") == "section"]
    text = "".join(words) if words else str(params.get("text", ""))
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


@pytest.fixture(scope="session")
def _fake_slack_server() -> Iterator[FakeSlack]:
    server = FakeSlack()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_slack(_fake_slack_server: FakeSlack) -> FakeSlack:
    _fake_slack_server.reset()
    return _fake_slack_server
