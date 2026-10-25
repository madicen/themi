"""A local fake of the Telegram Bot API, enough for Themi's channel.

    def test_pairing(fake_telegram, channel):
        fake_telegram.send_text(3001, "/start K7QM-3XRP")
        await channel.poll_once()
        assert fake_telegram.sent_texts(3001) == ["Hi Guest! ..."]

Updates are injected with `send_text`, `send_voice`, `tap` and `react`, and
returned by getUpdates according to the offset the client sends, so offset
handling is tested for real. Errors can be queued per method with `fail`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import count
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from tests.fakes._server import BackgroundServer

BOT_TOKEN = "123456789:FAKE-telegram-token-for-the-local-test-server"
BOT_USER = {"id": 123456789, "is_bot": True, "first_name": "Themi", "username": "themi_test_bot"}
NAMES = {1001: "Erin", 1002: "Husband"}


@dataclass
class ApiCall:
    method: str
    params: dict[str, Any]


@dataclass
class _Failure:
    status: int
    description: str
    retry_after: int | None = None


@dataclass
class FakeTelegramState:
    updates: list[dict[str, Any]] = field(default_factory=list)
    calls: list[ApiCall] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    failures: dict[str, list[_Failure]] = field(default_factory=dict)


class FakeTelegram:
    def __init__(self) -> None:
        self.state = FakeTelegramState()
        self._lock = threading.Lock()
        self._update_ids = count(1)
        self._message_ids = count(100)
        self._dates = count(1_790_000_000)
        self.app = FastAPI()
        self.app.add_api_route("/bot{token}/{method}", self._api, methods=["POST", "GET"])
        self.app.add_api_route("/file/bot{token}/{path:path}", self._file, methods=["GET"])
        self._background = BackgroundServer(self.app)

    # ----- wiring -------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return f"{self._background.url}/bot"

    @property
    def base_file_url(self) -> str:
        return f"{self._background.url}/file/bot"

    def start(self) -> None:
        self._background.start()

    def stop(self) -> None:
        self._background.stop()

    def reset(self) -> None:
        with self._lock:
            self.state = FakeTelegramState()

    # ----- injecting updates --------------------------------------------------

    def _user(self, user_id: int) -> dict[str, Any]:
        return {"id": user_id, "is_bot": False, "first_name": NAMES.get(user_id, "Someone")}

    def _chat(self, chat_id: int, chat_type: str) -> dict[str, Any]:
        chat: dict[str, Any] = {"id": chat_id, "type": chat_type}
        if chat_type == "private":
            chat["first_name"] = NAMES.get(chat_id, "Someone")
        else:
            chat["title"] = "Family"
        return chat

    def _push(self, kind: str, payload: dict[str, Any]) -> int:
        with self._lock:
            update_id = next(self._update_ids)
            self.state.updates.append({"update_id": update_id, kind: payload})
            return update_id

    def _message(self, user_id: int, chat_id: int | None, chat_type: str) -> dict[str, Any]:
        return {
            "message_id": next(self._message_ids),
            "date": next(self._dates),
            "chat": self._chat(chat_id if chat_id is not None else user_id, chat_type),
            "from": self._user(user_id),
        }

    def send_text(
        self, user_id: int, text: str, *, chat_id: int | None = None, chat_type: str = "private"
    ) -> int:
        message = self._message(user_id, chat_id, chat_type)
        message["text"] = text
        if text.startswith("/"):
            command = text.split()[0]
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(command)}]
        return self._push("message", message)

    def send_voice(self, user_id: int, data: bytes, *, duration: int = 4) -> int:
        file_id = f"voice-{len(self.state.files) + 1}"
        with self._lock:
            self.state.files[file_id] = data
        message = self._message(user_id, None, "private")
        message["voice"] = {
            "file_id": file_id,
            "file_unique_id": f"u-{file_id}",
            "duration": duration,
            "mime_type": "audio/ogg",
            "file_size": len(data),
        }
        return self._push("message", message)

    def tap(self, user_id: int, callback_data: str, message_id: int) -> int:
        return self._push(
            "callback_query",
            {
                "id": f"cq-{message_id}-{user_id}",
                "from": self._user(user_id),
                "chat_instance": "ci-1",
                "data": callback_data,
                "message": {
                    "message_id": message_id,
                    "date": next(self._dates),
                    "chat": self._chat(user_id, "private"),
                    "from": BOT_USER,
                    "text": "(the bot's message)",
                },
            },
        )

    def react(
        self, user_id: int, message_id: int, new: list[str], old: list[str] | None = None
    ) -> int:
        return self._push(
            "message_reaction",
            {
                "chat": self._chat(user_id, "private"),
                "message_id": message_id,
                "user": self._user(user_id),
                "date": next(self._dates),
                "old_reaction": [{"type": "emoji", "emoji": e} for e in old or []],
                "new_reaction": [{"type": "emoji", "emoji": e} for e in new],
            },
        )

    def fail(
        self,
        method: str,
        status: int = 502,
        description: str = "Bad Gateway",
        *,
        retry_after: int | None = None,
        times: int = 1,
    ) -> None:
        with self._lock:
            queue = self.state.failures.setdefault(method, [])
            queue.extend(_Failure(status, description, retry_after) for _ in range(times))

    # ----- inspecting what the bot did ----------------------------------------

    def calls(self, method: str) -> list[dict[str, Any]]:
        with self._lock:
            return [c.params for c in self.state.calls if c.method == method]

    def sent_texts(self, chat_id: int) -> list[str]:
        return [p["text"] for p in self.calls("sendMessage") if int(p["chat_id"]) == chat_id]

    def last_keyboard(self, chat_id: int) -> list[dict[str, Any]]:
        for params in reversed(self.calls("sendMessage")):
            if int(params["chat_id"]) == chat_id and params.get("reply_markup"):
                return params["reply_markup"]["inline_keyboard"][0]
        raise AssertionError(f"no keyboard was sent to {chat_id}")

    # ----- the HTTP side ------------------------------------------------------

    async def _params(self, request: Request) -> dict[str, Any]:
        body = await request.body()
        if not body:
            return dict(request.query_params)
        if request.headers.get("content-type", "").startswith("application/json"):
            return json.loads(body)
        form = await request.form()
        params: dict[str, Any] = {}
        for key, value in form.items():
            if not isinstance(value, str):
                continue
            try:
                params[key] = json.loads(value)
            except json.JSONDecodeError:
                params[key] = value
        return params

    async def _api(self, token: str, method: str, request: Request) -> Response:
        params = await self._params(request)
        with self._lock:
            self.state.calls.append(ApiCall(method, params))
            pending = self.state.failures.get(method)
            failure = pending.pop(0) if pending else None
        if token != BOT_TOKEN:
            return JSONResponse(
                {"ok": False, "error_code": 401, "description": "Unauthorized"}, status_code=401
            )
        if failure is not None:
            body: dict[str, Any] = {
                "ok": False,
                "error_code": failure.status,
                "description": failure.description,
            }
            if failure.retry_after is not None:
                body["parameters"] = {"retry_after": failure.retry_after}
            return JSONResponse(body, status_code=failure.status)
        return JSONResponse({"ok": True, "result": self._result(method, params)})

    def _result(self, method: str, params: dict[str, Any]) -> Any:
        if method == "getMe":
            return BOT_USER
        if method == "getUpdates":
            offset = int(params.get("offset") or 0)
            with self._lock:
                return [u for u in self.state.updates if u["update_id"] >= offset]
        if method in ("sendMessage", "editMessageText"):
            chat_id = int(params["chat_id"])
            message: dict[str, Any] = {
                "message_id": int(params.get("message_id") or next(self._message_ids)),
                "date": next(self._dates),
                "chat": self._chat(chat_id, "private"),
                "from": BOT_USER,
                "text": params["text"],
            }
            if params.get("reply_markup"):
                message["reply_markup"] = params["reply_markup"]
            return message
        if method == "getFile":
            file_id = params["file_id"]
            return {
                "file_id": file_id,
                "file_unique_id": f"u-{file_id}",
                "file_size": len(self.state.files.get(file_id, b"")),
                "file_path": f"voice/{file_id}.oga",
            }
        # deleteWebhook, sendChatAction, setMessageReaction, answerCallbackQuery,
        # setMyCommands, close, logOut...
        return True

    async def _file(self, token: str, path: str) -> Response:
        file_id = path.rsplit("/", 1)[-1].removesuffix(".oga")
        data = self.state.files.get(file_id)
        if data is None:
            return Response(status_code=404)
        return Response(content=data, media_type="application/octet-stream")


@pytest.fixture(scope="session")
def _fake_telegram_server() -> Iterator[FakeTelegram]:
    server = FakeTelegram()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_telegram(_fake_telegram_server: FakeTelegram) -> FakeTelegram:
    _fake_telegram_server.reset()
    return _fake_telegram_server
