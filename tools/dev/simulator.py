"""A Telegram stand-in you can use from a browser.

It's the fake Bot API from the tests, plus a chat page at `/`. Themi polls it
exactly as it polls Telegram (point `TELEGRAM_API_URL` at it), and the page
injects updates and shows everything the bot sends:

- pick a person: Erin, Husband, or someone new who hasn't paired yet
- send messages, tap inline buttons, react with ✅ or 💤
- see edits, the bot's own reactions, button answers and "typing…"
- skip Themi's clock ahead, so scheduled nudges fire now
- open the website signed in as the chosen person (`login` makes the link)

The page polls `/sim/state` for one chat's transcript.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from tests.fakes.telegram_api import NAMES, FakeTelegram
from themi import clock

PAGE = Path(__file__).with_name("simulator.html")
NEWCOMER_ID = 1003
PEOPLE = [
    *({"id": i, "name": n} for i, n in NAMES.items()),
    {"id": NEWCOMER_ID, "name": "Someone new"},
]
TYPING_SECONDS = 6.0  # Telegram shows a chat action for about 5 seconds


@dataclass
class Entry:
    seq: int
    chat_id: int
    sender: str  # "person", "bot" or "notice"
    text: str
    message_id: int | None = None
    buttons: list[dict[str, str]] = field(default_factory=list)
    reactions: list[str] = field(default_factory=list)  # the person's, on a bot message
    bot_reactions: list[str] = field(default_factory=list)  # the bot's, on a person's message
    edited: bool = False


class Simulator(FakeTelegram):
    def __init__(self, port: int = 0) -> None:
        super().__init__(port)
        self._entries: list[Entry] = []
        self._typing_until: dict[int, float] = {}
        self._sim_lock = threading.Lock()
        self.version = 0
        # Telegram user id -> a website sign-in link, or None if they aren't a member.
        self.login: Callable[[int], str | None] | None = None
        self.app.add_api_route("/", self._page, methods=["GET"], response_class=HTMLResponse)
        self.app.add_api_route("/sim/state", self._state, methods=["GET"])
        self.app.add_api_route("/sim/send", self._send, methods=["POST"])
        self.app.add_api_route("/sim/tap", self._tap, methods=["POST"])
        self.app.add_api_route("/sim/react", self._react, methods=["POST"])
        self.app.add_api_route("/sim/skip", self._skip, methods=["POST"])
        self.app.add_api_route("/sim/website", self._website, methods=["GET"])

    @property
    def url(self) -> str:
        return self.base_url.removesuffix("/bot")

    # ----- the transcript -----------------------------------------------------

    def transcript(self, chat_id: int) -> list[Entry]:
        with self._sim_lock:
            return [e for e in self._entries if e.chat_id == chat_id]

    def typing(self, chat_id: int) -> bool:
        return self._typing_until.get(chat_id, 0.0) > time.monotonic()

    def _add(self, chat_id: int, sender: str, text: str, **fields: Any) -> None:
        with self._sim_lock:
            self.version += 1
            self._entries.append(Entry(self.version, chat_id, sender, text, **fields))

    def _find(self, chat_id: int, message_id: int) -> Entry | None:
        for entry in reversed(self._entries):
            if entry.chat_id == chat_id and entry.message_id == message_id:
                return entry
        return None

    def _change(self, chat_id: int, message_id: int, **fields: Any) -> None:
        with self._sim_lock:
            entry = self._find(chat_id, message_id)
            if entry is None:
                return
            for name, value in fields.items():
                setattr(entry, name, value)
            self.version += 1

    # ----- hooks into the fake ------------------------------------------------

    def _push(self, kind: str, payload: dict[str, Any]) -> int:
        update_id = super()._push(kind, payload)
        if kind == "message":
            text = payload.get("text") or "(voice note)"
            self._add(payload["chat"]["id"], "person", text, message_id=payload["message_id"])
        elif kind == "message_reaction":
            emoji = [r["emoji"] for r in payload["new_reaction"]]
            self._change(payload["chat"]["id"], payload["message_id"], reactions=emoji)
        return update_id

    def _result(self, method: str, params: dict[str, Any]) -> Any:
        result = super()._result(method, params)
        chat_id = int(params.get("chat_id") or 0)
        if method == "sendMessage":
            self._typing_until.pop(chat_id, None)
            self._add(
                chat_id,
                "bot",
                params["text"],
                message_id=result["message_id"],
                buttons=_buttons(params),
            )
        elif method == "editMessageText":
            self._change(
                chat_id,
                int(params["message_id"]),
                text=params["text"],
                buttons=_buttons(params),
                edited=True,
            )
        elif method == "setMessageReaction":
            emoji = [r["emoji"] for r in params.get("reaction") or []]
            self._change(chat_id, int(params["message_id"]), bot_reactions=emoji)
        elif method == "sendChatAction":
            self._typing_until[chat_id] = time.monotonic() + TYPING_SECONDS
        elif method == "answerCallbackQuery" and params.get("text"):
            # Callback ids look like "cq-<message id>-<user id>" (see FakeTelegram.tap).
            user_id = int(str(params["callback_query_id"]).rsplit("-", 1)[-1])
            self._add(user_id, "notice", params["text"])
        return result

    # ----- the page's endpoints -----------------------------------------------

    async def _page(self) -> HTMLResponse:
        return HTMLResponse(PAGE.read_text())

    async def _state(self, chat: int) -> JSONResponse:
        with self._sim_lock:
            # The newest bot message in each chat, so the page can mark the others unread.
            latest = {p["id"]: 0 for p in PEOPLE}
            for entry in self._entries:
                if entry.sender == "bot" and entry.chat_id in latest:
                    latest[entry.chat_id] = entry.seq
            entries = [asdict(e) for e in self._entries if e.chat_id == chat]
        return JSONResponse(
            {
                "version": self.version,
                "people": PEOPLE,
                "latest": latest,
                "entries": entries,
                "typing": self.typing(chat),
                "now": clock.now().isoformat(),
                "skipped_minutes": int(clock.shifted_by().total_seconds() // 60),
            }
        )

    async def _send(self, request: Request) -> JSONResponse:
        body = await request.json()
        text = str(body.get("text", "")).strip()
        if not text:
            return JSONResponse({"ok": False, "error": "empty message"}, status_code=400)
        self.send_text(int(body["user_id"]), text)
        return JSONResponse({"ok": True})

    async def _tap(self, request: Request) -> JSONResponse:
        body = await request.json()
        self.tap(int(body["user_id"]), str(body["data"]), int(body["message_id"]))
        return JSONResponse({"ok": True})

    async def _react(self, request: Request) -> JSONResponse:
        body = await request.json()
        user_id, message_id = int(body["user_id"]), int(body["message_id"])
        with self._sim_lock:
            entry = self._find(user_id, message_id)
            old = list(entry.reactions) if entry else []
        new = [] if body["emoji"] in old else [str(body["emoji"])]  # tapping again removes it
        self.react(user_id, message_id, new, old)
        return JSONResponse({"ok": True})

    async def _website(self, person: int) -> Response:
        link = self.login(person) if self.login else None
        if link is None:
            return HTMLResponse("That person isn't a paired member yet.", status_code=404)
        return RedirectResponse(link, status_code=303)

    async def _skip(self, request: Request) -> JSONResponse:
        body = await request.json()
        minutes = int(body["minutes"])
        if not 0 < minutes <= 7 * 24 * 60:
            return JSONResponse({"ok": False, "error": "skip 1 minute to 7 days"}, status_code=400)
        now = clock.shift(timedelta(minutes=minutes))
        return JSONResponse({"ok": True, "now": now.isoformat()})


def _buttons(params: dict[str, Any]) -> list[dict[str, str]]:
    markup = params.get("reply_markup") or {}
    return [
        {"text": b["text"], "data": b.get("callback_data", "")}
        for row in markup.get("inline_keyboard", [])
        for b in row
    ]
