"""A Telegram stand-in you can use from a browser.

It's the fake Bot API from the tests, plus a chat page at `/`. Themi polls it
exactly as it polls Telegram (point `TELEGRAM_API_URL` at it), and the page
injects updates and shows everything the bot sends:

- pick a person: Erin, Husband, or someone new who hasn't paired yet
- send messages, tap inline buttons, react with ✅ or 💤
- see edits, the bot's own reactions, button answers and "typing…"
- skip Themi's clock ahead, so scheduled nudges fire now
- open the website signed in as the chosen person (`login` makes the link)
- copy the test session (conversations and Themi's log) as text, from `/sim/report`

The page polls `/sim/state` for one chat's transcript. Entries in chat 0
(skips, session marks) show in every chat.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from tests.fakes.telegram_api import NAMES, FakeTelegram
from themi import clock
from themi.logs import RedactingFormatter

PAGE = Path(__file__).with_name("simulator.html")
NEWCOMER_ID = 1003
PEOPLE = [
    *({"id": i, "name": n} for i, n in NAMES.items()),
    {"id": NEWCOMER_ID, "name": "Someone new"},
]
TYPING_SECONDS = 6.0  # Telegram shows a chat action for about 5 seconds
EVERY_CHAT = 0  # entries shown in all chats: skips and session marks
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"  # as on the console


@dataclass
class Entry:
    seq: int
    chat_id: int
    sender: str  # "person", "bot", "action" (a tap or reaction) or "notice"
    text: str
    message_id: int | None = None
    buttons: list[dict[str, str]] = field(default_factory=list)
    reactions: list[str] = field(default_factory=list)  # the person's, on a bot message
    bot_reactions: list[str] = field(default_factory=list)  # the bot's, on a person's message
    edited: bool = False
    previous: list[str] = field(default_factory=list)  # earlier texts, oldest first
    at: str = ""  # wall-clock time, to match the log lines
    themi_at: str = ""  # Themi's clock, which runs ahead after a skip
    changed: int = 0  # the version of the last edit or reaction


class LogBuffer(logging.Handler):
    """Keeps the most recent log lines, redacted, for the session report."""

    def __init__(self, capacity: int = 5000) -> None:
        super().__init__()
        self.setFormatter(RedactingFormatter(LOG_FORMAT))
        self._lines: deque[tuple[int, str]] = deque(maxlen=capacity)
        self._lines_lock = threading.Lock()
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            self.handleError(record)
            return
        with self._lines_lock:
            self.count += 1
            self._lines.append((self.count, line))

    def since(self, count: int) -> list[str]:
        with self._lines_lock:
            return [line for n, line in self._lines if n > count]


class Simulator(FakeTelegram):
    def __init__(self, port: int = 0) -> None:
        super().__init__(port)
        self._entries: list[Entry] = []
        self._typing_until: dict[int, float] = {}
        self._sim_lock = threading.Lock()
        self.version = 0
        self.logs = LogBuffer()  # the dev runner adds it to the root logger
        self._session_seq = 0  # entries after this version are in the report
        self._session_log = 0
        self._session_at = _wall_clock()
        # Telegram user id -> a website sign-in link, or None if they aren't a member.
        self.login: Callable[[int], str | None] | None = None
        self.app.add_api_route("/", self._page, methods=["GET"], response_class=HTMLResponse)
        self.app.add_api_route("/sim/state", self._state, methods=["GET"])
        self.app.add_api_route("/sim/send", self._send, methods=["POST"])
        self.app.add_api_route("/sim/tap", self._tap, methods=["POST"])
        self.app.add_api_route("/sim/react", self._react, methods=["POST"])
        self.app.add_api_route("/sim/skip", self._skip, methods=["POST"])
        self.app.add_api_route("/sim/website", self._website, methods=["GET"])
        self.app.add_api_route("/sim/report", self._report, methods=["GET"])
        self.app.add_api_route("/sim/session", self._new_session, methods=["POST"])

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
            entry = Entry(self.version, chat_id, sender, text, **fields)
            entry.at, entry.themi_at = _wall_clock().isoformat(), clock.now().isoformat()
            self._entries.append(entry)

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
            if "text" in fields and fields["text"] != entry.text:
                entry.previous.append(entry.text)
            for name, value in fields.items():
                setattr(entry, name, value)
            self.version += 1
            entry.changed = self.version

    # ----- hooks into the fake ------------------------------------------------

    def _push(self, kind: str, payload: dict[str, Any]) -> int:
        update_id = super()._push(kind, payload)
        if kind == "message":
            text = payload.get("text") or "(voice note)"
            self._add(payload["chat"]["id"], "person", text, message_id=payload["message_id"])
        elif kind == "message_reaction":
            chat_id, message_id = payload["chat"]["id"], payload["message_id"]
            emoji = [r["emoji"] for r in payload["new_reaction"]]
            self._change(chat_id, message_id, reactions=emoji)
            what = f"reacted {''.join(emoji)}" if emoji else "removed their reaction"
            self._add(chat_id, "action", f"{what} on message {message_id}")
        elif kind == "callback_query":
            message = payload["message"]
            chat_id, message_id = message["chat"]["id"], message["message_id"]
            with self._sim_lock:
                entry = self._find(chat_id, message_id)
                labels = {b["data"]: b["text"] for b in entry.buttons} if entry else {}
            label = labels.get(payload["data"], payload["data"])
            self._add(chat_id, "action", f'tapped "{label}" on message {message_id}')
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
            entries = [asdict(e) for e in self._entries if e.chat_id in (chat, EVERY_CHAT)]
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
        self._add(EVERY_CHAT, "notice", f"Skipped ahead {_duration(minutes)}")
        return JSONResponse({"ok": True, "now": now.isoformat()})

    # ----- the session report -------------------------------------------------

    def new_session(self) -> None:
        self._add(EVERY_CHAT, "notice", "New test session")
        with self._sim_lock:
            self._session_seq = self.version - 1  # the mark itself starts the report
        self._session_log = self.logs.count
        self._session_at = _wall_clock()

    def report(self) -> str:
        """The current test session as text: each conversation, then Themi's log."""
        with self._sim_lock:
            fresh = [e for e in self._entries if max(e.seq, e.changed) > self._session_seq]
        everywhere = [e for e in fresh if e.chat_id == EVERY_CHAT]
        skipped = int(clock.shifted_by().total_seconds() // 60)
        lines = [
            "# Themi simulator session",
            "",
            f"Copied {_wall_clock():%a %d %b %Y %H:%M:%S %Z}. "
            f"Session started {self._session_at:%H:%M:%S}.",
            f"Themi's clock: {clock.now().astimezone():%a %d %b %H:%M}"
            + (f" (skipped ahead {_duration(skipped)})." if skipped else "."),
            "Times are this computer's clock, to match the log; Themi's clock is shown "
            "when it differs.",
        ]
        for person in PEOPLE:
            own = [e for e in fresh if e.chat_id == person["id"]]
            if not own:
                continue
            lines += ["", f"## {person['name']} (Telegram {person['id']})", ""]
            for entry in sorted(own + everywhere, key=lambda e: e.seq):
                lines += _report_lines(entry, person["name"])
        logs = self.logs.since(self._session_log)
        lines += ["", f"## Themi log ({len(logs)} lines)", ""]
        lines += logs or ["(nothing logged)"]
        return "\n".join(lines) + "\n"

    async def _report(self) -> PlainTextResponse:
        return PlainTextResponse(self.report())

    async def _new_session(self) -> JSONResponse:
        self.new_session()
        return JSONResponse({"ok": True})


def _wall_clock() -> datetime:
    return datetime.now(UTC).astimezone()


def _duration(minutes: int) -> str:
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    parts = [f"{days}d" if days else "", f"{hours}h" if hours else "", f"{mins}m" if mins else ""]
    return " ".join(p for p in parts if p)


def _report_lines(entry: Entry, name: str) -> list[str]:
    at = datetime.fromisoformat(entry.at)
    themi_at = datetime.fromisoformat(entry.themi_at).astimezone()
    stamp = f"{at:%H:%M:%S}"
    if abs(themi_at - at) >= timedelta(minutes=1):
        stamp += f", Themi {themi_at:%a %H:%M}"
    if entry.sender == "notice" and entry.chat_id == EVERY_CHAT:
        return [f"[{stamp}] -- {entry.text} --"]
    if entry.sender == "notice":
        return [f'[{stamp}] Themi answered the tap: "{entry.text}"']
    if entry.sender == "action":
        return [f"[{stamp}] {name} {entry.text}"]
    label = f"{name if entry.sender == 'person' else 'Themi'} #{entry.message_id}"
    if entry.previous:
        earlier = (t.replace("\n", " / ") for t in entry.previous)  # one line each
        label += " (edited; earlier: " + " | ".join(f'"{t}"' for t in earlier) + ")"
    first, *rest = entry.text.split("\n")
    lines = [f"[{stamp}] {label}: {first}", *(f"    {line}" for line in rest)]
    if entry.buttons:
        lines.append("    buttons: " + " ".join(f"[{b['text']}]" for b in entry.buttons))
    if entry.bot_reactions:
        lines.append(f"    Themi reacted {''.join(entry.bot_reactions)}")
    return lines


def _buttons(params: dict[str, Any]) -> list[dict[str, str]]:
    markup = params.get("reply_markup") or {}
    return [
        {"text": b["text"], "data": b.get("callback_data", "")}
        for row in markup.get("inline_keyboard", [])
        for b in row
    ]
