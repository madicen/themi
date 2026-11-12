"""CR20b: the channels a Themi has, as one channel for the core (the outbox, the agent).

Each channel module adds its channel (`ctx.channel`). What a channel receives goes to the
agent as before; the set notes which channel each person last wrote from. What Themi sends
goes there, so an answer comes back where they asked; otherwise to the first channel
they're on (Telegram in the family's), and to the first channel when they're on none (as
before channels were modules: a send to someone not paired fails there).

Edits go the same way as sends, so an edit reaches the message it changes as long as the
person hasn't moved channels in between.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi.channels.base import Channel
    from themi.channels.events import Button, InboundEvent, InboundHandler


class _Noted:
    """A channel's own handler: notes where the person wrote from, then hands it on."""

    def __init__(self, channels: ChannelSet, name: str) -> None:
        self.channels = channels
        self.name = name

    async def handle(self, event: InboundEvent, channel: Channel) -> None:
        self.channels.last_used[event.member.id] = self.name
        if self.channels.handler is not None:
            await self.channels.handler.handle(event, channel)


class ChannelSet:
    def __init__(self) -> None:
        self.channels: dict[str, Channel] = {}  # in the order they were added
        self.last_used: dict[int, str] = {}  # member id -> the channel they last wrote from
        self._handler: InboundHandler | None = None

    # ----- the set --------------------------------------------------------------------

    def add(self, name: str, channel: Channel) -> None:
        self.channels[name] = channel
        channel.handler = _Noted(self, name)

    def get(self, name: str) -> Channel | None:
        return self.channels.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self.channels

    @property
    def handler(self) -> InboundHandler | None:
        return self._handler

    @handler.setter
    def handler(self, handler: InboundHandler | None) -> None:
        self._handler = handler

    def channel_for(self, member: Member) -> Channel:
        """Where to write to them: where they last wrote from, else the first channel
        they're on, else the first channel."""
        if not self.channels:
            raise LookupError("this Themi has no channel to write on")
        last = self.last_used.get(member.id)
        if last in self.channels and last in member.channels:
            return self.channels[last]
        for name, channel in self.channels.items():
            if name in member.channels:
                return channel
        return next(iter(self.channels.values()))

    # ----- as one channel -------------------------------------------------------------

    @property
    def last_poll_at(self) -> datetime | None:
        polls = [c.last_poll_at for c in self.channels.values() if c.last_poll_at is not None]
        return max(polls) if polls else None

    async def start(self) -> None:
        for channel in self.channels.values():
            await channel.start()

    async def stop(self) -> None:
        for channel in self.channels.values():
            await channel.stop()

    async def run(self, stop: asyncio.Event | None = None) -> None:
        await asyncio.gather(*(c.run(stop) for c in self.channels.values()))

    async def poll_once(self) -> int:
        """Each channel that polls, once (the tests', and the simulator's)."""
        total = 0
        for channel in self.channels.values():
            poll = getattr(channel, "poll_once", None)
            if poll is not None:
                total += await poll()
        return total

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
        channel = self._group() if chat_id is not None else self.channel_for(member)
        return await channel.send_text(
            member,
            text,
            buttons,
            kind=kind,
            link_preview=link_preview,
            chat_id=chat_id,
            anyone=anyone,
        )

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
        channel = self._group() if chat_id is not None else self.channel_for(member)
        await channel.edit_text(member, message_id, text, buttons, chat_id=chat_id, anyone=anyone)

    @asynccontextmanager
    async def typing(self, member: Member) -> AsyncIterator[None]:
        async with self.channel_for(member).typing(member):
            yield

    async def publish_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        for channel in self.channels.values():
            await channel.publish_commands(commands)

    async def send_photo(
        self, member: Member, photo: bytes, caption: str = "", *, kind: str = "photo"
    ) -> int:
        send: Any = getattr(self.channel_for(member), "send_photo", None)
        if send is None:
            raise NotImplementedError("this channel can't send pictures")
        return await send(member, photo, caption, kind=kind)

    async def send_document(
        self, member: Member, data: bytes, filename: str, caption: str = "", *,
        kind: str = "document",
    ) -> int:  # fmt: skip
        send: Any = getattr(self.channel_for(member), "send_document", None)
        if send is None:
            raise NotImplementedError("this channel can't send files")
        return await send(member, data, filename, caption, kind=kind)

    async def react(self, member: Member, message_id: int, emoji: str) -> None:
        react: Any = getattr(self.channel_for(member), "react", None)
        if react is not None:
            await react(member, message_id, emoji)

    def _group(self) -> Channel:
        """A group chat's channel: the first that has groups (Telegram's family group)."""
        for channel in self.channels.values():
            if hasattr(channel, "family_group"):
                return channel
        return next(iter(self.channels.values()))
