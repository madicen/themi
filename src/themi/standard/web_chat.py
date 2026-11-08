"""CR20b: a chat with Themi on the website (`/chat`), as a channel. For someone who uses only
the site, or who'd rather type at a computer: what they write goes to the agent like a
Telegram message, and Themi's answers and nudges come back here, buttons as buttons.

Opening the page puts them on the channel (an identity, "web_chat"), so Themi can reach
them here. Themi answers on the channel they last wrote from (the channel set).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi import clock
from themi.accounts import AccountStore, Member
from themi.channels.events import Button, ButtonPress, InboundEvent, InboundHandler
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi.modules.web import MenuEntry

if TYPE_CHECKING:
    from themi.web.kit import Kit

NAME = "web_chat"
SHOWN = 60  # the page shows the latest messages


@dataclass(frozen=True)
class ChatMessage:
    id: int
    direction: str  # "in": theirs; "out": Themi's
    text: str
    buttons: tuple[str, ...]  # labels; a tap sends the button's index
    created_at: str


class WebChatChannel:
    def __init__(self, store: AccountStore) -> None:
        self.store = store
        self.db = store.db
        self.handler: InboundHandler | None = None
        self.last_poll_at: datetime | None = None  # nothing to poll: the site brings messages

    # ----- the channel ----------------------------------------------------------------

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

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
        yield  # the page waits for the answer anyway

    async def publish_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        pass

    # ----- the page's side ------------------------------------------------------------

    def join(self, member: Member) -> Member:
        """Put them on this channel, so Themi can write to them here."""
        if self.store.identity(member.id, NAME) is None:
            self.store.set_identity(member.id, NAME, str(member.id))
        return self.store.get_member(member.id)

    async def receive(self, member: Member, text: str) -> None:
        member = self.join(member)
        message_id = self._keep(member.id, "in", text, ())
        await self._hand_on(InboundEvent("text", member, member.id, message_id, clock.now(), 0,
                                         text=text))  # fmt: skip

    async def press(self, member: Member, message_id: int, index: int) -> bool:
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
        await self._hand_on(event)
        return True

    def messages(self, member: Member, limit: int = SHOWN) -> list[ChatMessage]:
        rows = self.db.query(
            "SELECT * FROM web_chat_messages WHERE member_id = ? ORDER BY id DESC LIMIT ?",
            (member.id, limit),
        )
        return [
            ChatMessage(
                r["id"],
                r["direction"],
                r["text"],
                tuple(b["label"] for b in json.loads(r["buttons"])),
                r["created_at"],
            )
            for r in reversed(rows)
        ]

    async def _hand_on(self, event: InboundEvent) -> None:
        if self.handler is not None:
            await self.handler.handle(event, self)

    def _keep(self, member_id: int, direction: str, text: str, buttons: Sequence[Button]) -> int:
        return self.db.execute(
            "INSERT INTO web_chat_messages (member_id, direction, text, buttons, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (member_id, direction, text, _buttons(buttons), to_utc_iso(clock.now())),
        )


def _buttons(buttons: Sequence[Button]) -> str:
    return json.dumps(
        [{"label": b.label, "kind": b.kind, "payload": b.payload} for b in buttons if not b.web_app]
    )


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    chat: WebChatChannel = kit.app.services.get(WebChatChannel)

    @router.get("/chat", response_class=HTMLResponse)
    def chat_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        member = chat.join(session.member)
        return kit.with_flash(request, "chat.html", session, messages=chat.messages(member))

    @router.post("/chat")
    async def say(request: Request) -> Response:
        session, form = await kit.checked(request)
        text = str(form.get("text", "")).strip()
        if text:
            await chat.receive(session.member, text)
        return kit.redirect("/chat#latest", "")

    @router.post("/chat/{message_id}/{index}")
    async def tap(request: Request, message_id: int, index: int) -> Response:
        session, _ = await kit.checked(request)
        if not await chat.press(session.member, message_id, index):
            return kit.redirect("/chat", "That button isn't there any more.")
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
