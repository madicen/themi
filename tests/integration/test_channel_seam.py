"""CR20a1: the core talks to a `Channel`, not to Telegram. A channel that isn't Telegram
carries a message in and Themi's reply out."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from itertools import count

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import ModelBank
from themi import clock
from themi.accounts import Member
from themi.app import build_app
from themi.channels.base import Channel
from themi.channels.events import Button, InboundEvent, InboundHandler
from themi.channels.telegram import TelegramChannel
from themi.storage.secrets import Secret


class LetterChannel:
    """A made-up channel: messages are kept in a list, as a website chat might keep them."""

    def __init__(self) -> None:
        self.handler: InboundHandler | None = None
        self.last_poll_at: datetime | None = None
        self.sent: list[tuple[int, str, tuple[str, ...]]] = []
        self._ids = count(1)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def run(self, stop: asyncio.Event | None = None) -> None:
        pass

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
        self.sent.append((member.id, text, tuple(b.label for b in buttons)))
        return next(self._ids)

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
        pass

    @asynccontextmanager
    async def typing(self, member: Member) -> AsyncIterator[None]:
        yield

    async def publish_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        pass


def test_telegram_is_a_channel(fake_telegram: FakeTelegram, family: SeededFamily) -> None:
    channel = TelegramChannel.from_token(Secret("1:x"), family.store, None)
    assert isinstance(channel, Channel)
    assert isinstance(LetterChannel(), Channel)


async def test_a_channel_that_isnt_telegram_carries_a_reply(family: SeededFamily) -> None:
    letters = LetterChannel()
    models = ModelBank()
    app = build_app(family.db, family.store.cipher, lambda _store: letters, provider_factory=models)
    assert app.channel is letters and letters.handler is not None
    erin = family.erin
    ai = app.ai_settings
    backend = ai.add_backend(erin, erin.id, "Primary", "ollama", model="primary")
    from themi.ai.settings import AITask, RouteEntry

    for task in AITask:
        ai.set_chain(erin, erin.id, task, [RouteEntry(backend.id)])
    models["primary"].queue_text("Hello from somewhere else.")
    event = InboundEvent("text", erin, 1, 1, clock.now(), 1, text="Hi Themi")
    await letters.handler.handle(event, letters)
    await app.outbox.flush()
    assert (erin.id, "Hello from somewhere else.", ()) in letters.sent
