"""CR20a1: how the core talks to people, whatever carries the words (Telegram today; the
website's chat, Discord or Slack later).

A channel receives messages and taps and passes each to its `handler` (the agent) as an
`InboundEvent`, and sends what the outbox gives it. The outbox, the agent and the runtime
name this protocol, never a channel's own class. A channel without reactions or pictures
leaves those methods out: the outbox checks for them (`getattr`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi.channels.events import Button, InboundHandler


@runtime_checkable
class Channel(Protocol):
    handler: InboundHandler | None  # who each message, tap or reaction goes to
    last_poll_at: datetime | None  # when it last asked for messages (/health); None: never

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def run(self, stop: asyncio.Event | None = None) -> None:
        """Receive until `stop` is set, passing each event to `handler`."""
        ...

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
        """Send to the member (or to a group chat, `chat_id`), returning the message's id;
        `anyone`: its buttons are for anyone in a group, not only the member."""
        ...

    async def edit_text(
        self,
        member: Member,
        message_id: int,
        text: str,
        buttons: Sequence[Button] = (),
        *,
        chat_id: int | None = None,
        anyone: bool = False,
    ) -> None: ...

    def typing(self, member: Member) -> AbstractAsyncContextManager[None]:
        """Show that Themi is writing for as long as the block runs."""
        ...

    async def publish_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        """The command menu, where the channel has one."""
        ...


class Pictures(Protocol):
    """A channel that can send a picture (BD4b's step pictures)."""

    async def send_photo(
        self,
        member: Member,
        photo: bytes,
        caption: str = "",
        *,
        kind: str = "photo",
        buttons: Sequence[Button] = (),
    ) -> int: ...


class Reactions(Protocol):
    """A channel that can put an emoji on a message (the sidecar's 👀)."""

    async def react(self, member: Member, message_id: int, emoji: str) -> None: ...
