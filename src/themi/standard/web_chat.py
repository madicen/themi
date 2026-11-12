"""CR20b: a chat with Themi on the website (`/chat`), as a channel. For someone who uses only
the site, or who'd rather type at a computer: what they write goes to the agent like a
Telegram message, and Themi's answers and nudges come back here, buttons as buttons.

Opening the page puts them on the channel (an identity, "web_chat"), so Themi can reach
them here. Themi answers on the channel they last wrote from (the channel set).

WC1: what the simulator showed, for the family. The conversation updates itself (the page
polls `/chat/log`, which answers 204 while nothing changed), sending doesn't reload the page,
"Themi is typing…" shows while it answers, edits are marked, reactions go both ways (theirs
on Themi's messages are `reaction` events, as on Telegram), and a message can reply to
another. Without JavaScript the page still works with plain forms.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi import clock
from themi.accounts import AccountStore, Member
from themi.channels.events import Button, ButtonPress, InboundEvent, InboundHandler, Reaction
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi.modules.web import MenuEntry

if TYPE_CHECKING:
    from themi.web.kit import Kit

log = logging.getLogger(__name__)

NAME = "web_chat"
SHOWN = 60  # the page shows the latest messages
REACTIONS = ("👍", "👎", "✅", "💤")  # under Themi's messages: liked, wrong, approve, snooze
REACTION_TITLES = {
    "👍": "Good answer",
    "👎": "Wrong answer",
    "✅": "Yes (approves a card)",
    "💤": "Later (snoozes a card)",
}
QUOTE = 80  # characters of the message a reply quotes


@dataclass(frozen=True)
class ChatMessage:
    id: int
    direction: str  # "in": theirs; "out": Themi's
    text: str
    buttons: tuple[str, ...]  # labels; a tap sends the button's index
    created_at: str
    edited: bool = False
    reactions: tuple[str, ...] = ()  # on Themi's: theirs; on theirs: Themi's
    quote: str = ""  # the start of the message this one replies to


class WebChatChannel:
    def __init__(self, store: AccountStore) -> None:
        self.store = store
        self.db = store.db
        self.handler: InboundHandler | None = None
        self.last_poll_at: datetime | None = None  # nothing to poll: the site brings messages
        self._typing: dict[int, int] = {}  # member id -> typing blocks running for them
        self._answering: set[asyncio.Task[None]] = set()  # answers the page didn't wait for

    # ----- the channel ----------------------------------------------------------------

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        await self.settle()

    async def run(self, stop: asyncio.Event | None = None) -> None:
        if stop is not None:
            await stop.wait()

    async def send_text(
        self,
        member: Member,
        text: str,
        buttons: Sequence[Button] = (),
        *,
        kind: str = "chat",
        link_preview: bool = True,
        chat_id: int | None = None,
        anyone: bool = False,
    ) -> int:
        return self._keep(member.id, "out", text, buttons)

    async def edit_text(
        self,
        member: Member,
        message_id: int,
        text: str,
        buttons: Sequence[Button] = (),
        *,
        chat_id: int | None = None,
        anyone: bool = False,
    ) -> None:
        self.db.execute(
            "UPDATE web_chat_messages SET text = ?, buttons = ?, edited_at = ? "
            "WHERE id = ? AND member_id = ?",
            (text, _buttons(buttons), to_utc_iso(clock.now()), message_id, member.id),
        )

    @asynccontextmanager
    async def typing(self, member: Member) -> AsyncIterator[None]:
        self._typing[member.id] = self._typing.get(member.id, 0) + 1
        try:
            yield
        finally:
            left = self._typing[member.id] - 1
            if left:
                self._typing[member.id] = left
            else:
                del self._typing[member.id]

    async def react(self, member: Member, message_id: int, emoji: str) -> None:
        """Themi's reaction on one of their messages (👀 while it reads, ✍ and the like)."""
        self.db.execute(
            "UPDATE web_chat_messages SET reactions = ? WHERE id = ? AND member_id = ? "
            "AND direction = 'in'",
            (json.dumps([emoji] if emoji else []), message_id, member.id),
        )

    async def publish_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        pass

    # ----- the page's side ------------------------------------------------------------

    def join(self, member: Member) -> Member:
        """Put them on this channel, so Themi can write to them here."""
        if self.store.identity(member.id, NAME) is None:
            self.store.set_identity(member.id, NAME, str(member.id))
        return self.store.get_member(member.id)

    def is_typing(self, member: Member) -> bool:
        return member.id in self._typing

    async def receive(
        self, member: Member, text: str, reply_to: int | None = None, *, wait: bool = True
    ) -> None:
        """What they wrote. `wait=False` keeps it and lets the agent answer in the background
        (the page shows the answer when it comes); a reply to a message not theirs is
        taken as a plain message."""
        member = self.join(member)
        if reply_to is not None and self._row(member, reply_to) is None:
            reply_to = None
        message_id = self._keep(member.id, "in", text, (), reply_to)
        event = InboundEvent("text", member, member.id, message_id, clock.now(), 0, text=text,
                             reply_to_message_id=reply_to)  # fmt: skip
        await self._answer(event, wait)

    async def react_as(self, member: Member, message_id: int, emoji: str) -> bool:
        """Their reaction on one of Themi's messages. One at a time, as on Telegram: the same
        emoji again takes it off. Adding one goes to the agent as a `reaction` event. False
        when there's no such message of Themi's to them, or no such reaction."""
        row = self._row(member, message_id, "out")
        if row is None or emoji not in REACTIONS:
            return False
        now = [] if json.loads(row["reactions"]) == [emoji] else [emoji]
        self.db.execute(
            "UPDATE web_chat_messages SET reactions = ? WHERE id = ?",
            (json.dumps(now), message_id),
        )
        if now:
            member = self.join(member)
            event = InboundEvent("reaction", member, member.id, message_id, clock.now(), 0,
                                 reaction=Reaction(tuple(now), message_id))  # fmt: skip
            await self._answer(event, wait=True)
        return True

    async def press(
        self, member: Member, message_id: int, index: int, *, wait: bool = True
    ) -> bool:
        """A tap on one of Themi's buttons. False when there's no such button of theirs."""
        row = self.db.one(
            "SELECT buttons FROM web_chat_messages WHERE id = ? AND member_id = ? "
            "AND direction = 'out'",
            (message_id, member.id),
        )
        buttons = json.loads(row["buttons"]) if row is not None else []
        if not 0 <= index < len(buttons):
            return False
        b = buttons[index]
        press = ButtonPress(b["label"], b["kind"], b["payload"], message_id)
        member = self.join(member)
        event = InboundEvent("button", member, member.id, message_id, clock.now(), 0, button=press)
        await self._answer(event, wait)
        return True

    def messages(self, member: Member, limit: int = SHOWN) -> list[ChatMessage]:
        rows = self.db.query(
            "SELECT m.*, r.text AS quoted FROM web_chat_messages m "
            "LEFT JOIN web_chat_messages r ON r.id = m.reply_to "
            "WHERE m.member_id = ? ORDER BY m.id DESC LIMIT ?",
            (member.id, limit),
        )
        return [
            ChatMessage(
                r["id"],
                r["direction"],
                r["text"],
                tuple(b["label"] for b in json.loads(r["buttons"])),
                r["created_at"],
                edited=r["edited_at"] is not None,
                reactions=tuple(json.loads(r["reactions"])),
                quote=_quote(r["quoted"]),
            )
            for r in reversed(rows)
        ]

    def quote(self, member: Member, message_id: int | None) -> str:
        """The start of one of their conversation's messages ("" if it isn't one)."""
        row = self._row(member, message_id) if message_id is not None else None
        return _quote(row["text"]) if row is not None else ""

    async def settle(self) -> None:
        """Wait for the answers still being worked out (tests; stopping)."""
        while self._answering:
            await asyncio.gather(*self._answering, return_exceptions=True)

    async def _answer(self, event: InboundEvent, wait: bool) -> None:
        if wait:
            await self._hand_on(event)
            return
        task = asyncio.create_task(self._hand_on(event))
        self._answering.add(task)
        task.add_done_callback(self._answered)

    def _answered(self, task: asyncio.Task[None]) -> None:
        self._answering.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("The website chat's answer failed", exc_info=task.exception())

    async def _hand_on(self, event: InboundEvent) -> None:
        if self.handler is not None:
            await self.handler.handle(event, self)

    def _row(self, member: Member, message_id: int, direction: str | None = None) -> Any:
        row = self.db.one(
            "SELECT * FROM web_chat_messages WHERE id = ? AND member_id = ?",
            (message_id, member.id),
        )
        if row is None or (direction is not None and row["direction"] != direction):
            return None
        return row

    def _keep(
        self,
        member_id: int,
        direction: str,
        text: str,
        buttons: Sequence[Button],
        reply_to: int | None = None,
    ) -> int:
        return self.db.execute(
            "INSERT INTO web_chat_messages "
            "(member_id, direction, text, buttons, created_at, reply_to) VALUES (?, ?, ?, ?, ?, ?)",
            (member_id, direction, text, _buttons(buttons), to_utc_iso(clock.now()), reply_to),
        )


def _version(values: dict[str, Any]) -> str:
    """Changes whenever what the log shows does: a message, an edit, a reaction, typing."""
    seen = repr((values["messages"], values["typing"], values["notice"]))
    return hashlib.sha256(seen.encode()).hexdigest()[:16]


def _quote(text: str | None) -> str:
    if not text:
        return ""
    line = " ".join(text.split())
    return line if len(line) <= QUOTE else line[: QUOTE - 1].rstrip() + "…"


def _buttons(buttons: Sequence[Button]) -> str:
    return json.dumps(
        [{"label": b.label, "kind": b.kind, "payload": b.payload} for b in buttons if not b.web_app]
    )


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    chat: WebChatChannel = kit.app.services.get(WebChatChannel)

    def log_values(member: Member, notice: str = "") -> dict[str, Any]:
        return {
            "messages": chat.messages(member),
            "typing": chat.is_typing(member),
            "notice": notice,
            "reactions": REACTIONS,
            "reaction_titles": REACTION_TITLES,
        }

    def the_log(request: Request, session: Any, notice: str = "") -> HTMLResponse:
        """The conversation as a fragment, carrying its version for the next poll."""
        values = log_values(session.member, notice)
        return kit.page(
            request, "_chat_log.html", member=session.member, csrf=session.csrf_token,
            version=_version(values), **values,
        )  # fmt: skip

    def htmx(request: Request) -> bool:
        return bool(request.headers.get("HX-Request"))

    @router.get("/chat", response_class=HTMLResponse)
    def chat_page(request: Request, reply: int | None = None) -> HTMLResponse:
        session = kit.current(request)
        member = chat.join(session.member)
        quote = chat.quote(member, reply)
        values = log_values(member)
        return kit.with_flash(
            request, "chat.html", session, version=_version(values),
            reply_to=reply if quote else None, reply_quote=quote, **values,
        )  # fmt: skip

    @router.get("/chat/log")
    def chat_log(request: Request, v: str = "") -> Response:
        """The conversation for the page's poll; 204 while it hasn't changed."""
        session = kit.current(request)
        if v and v == _version(log_values(session.member)):
            return Response(status_code=204)
        return the_log(request, session)

    @router.post("/chat")
    async def say(request: Request) -> Response:
        session, form = await kit.checked(request)
        text = str(form.get("text", "")).strip()
        reply = str(form.get("reply_to", "")).strip()
        reply_to = int(reply) if reply.isdigit() else None
        if text:
            await chat.receive(session.member, text, reply_to, wait=not htmx(request))
        if htmx(request):
            return the_log(request, session)
        return kit.redirect("/chat#latest", "")

    @router.post("/chat/{message_id}/react")
    async def react(request: Request, message_id: int) -> Response:
        session, form = await kit.checked(request)
        if not await chat.react_as(session.member, message_id, str(form.get("emoji", ""))):
            gone = "That message isn't there any more."
            return the_log(request, session, gone) if htmx(request) else kit.redirect("/chat", gone)
        if htmx(request):
            return the_log(request, session)
        return kit.redirect(f"/chat#m{message_id}", "")

    @router.post("/chat/{message_id}/{index}")
    async def tap(request: Request, message_id: int, index: int) -> Response:
        session, _ = await kit.checked(request)
        if not await chat.press(session.member, message_id, index, wait=not htmx(request)):
            gone = "That button isn't there any more."
            return the_log(request, session, gone) if htmx(request) else kit.redirect("/chat", gone)
        if htmx(request):
            return the_log(request, session)
        return kit.redirect("/chat#latest", "")

    return router


class WebChatModule(Module):
    """A chat with Themi on the website."""

    name = NAME
    title = "Website chat"
    summary = "Anyone in the family can chat with Themi on its website."
    kind = "channel"
    migrations = Path(__file__).parent / "web_chat_schema"
    website = "Anyone can talk to Themi on the Chat page (/chat)."

    def install(self, ctx: ModuleContext) -> None:
        from themi.web import icons

        channel = ctx.provide(WebChatChannel(ctx.services.store))
        ctx.channel(NAME, channel)
        ctx.web(
            routes,
            MenuEntry("/chat", "Chat", "Talk with Themi here", "You", 1, icon=icons.TASKS),
        )
