"""Smoke test against the real Telegram Bot API. Opt-in: `make test-live`.

Needs a separate test bot, never the family's:
- THEMI_LIVE_TELEGRAM_TOKEN     the test bot's token (from @BotFather)
- THEMI_LIVE_TELEGRAM_CHAT_ID   a chat with that bot (send it /start once, then read the
                                chat id from getUpdates)
"""

from __future__ import annotations

import os

import pytest

from tests.fixtures.family import SeededFamily
from themi.accounts import SYSTEM, Role
from themi.channels.events import Button
from themi.channels.telegram import TelegramChannel
from themi.storage.secrets import Secret

TOKEN = os.environ.get("THEMI_LIVE_TELEGRAM_TOKEN")
CHAT = os.environ.get("THEMI_LIVE_TELEGRAM_CHAT_ID")

pytestmark = pytest.mark.skipif(
    not (TOKEN and CHAT), reason="set THEMI_LIVE_TELEGRAM_TOKEN and THEMI_LIVE_TELEGRAM_CHAT_ID"
)


async def test_send_edit_and_poll(family: SeededFamily) -> None:
    assert TOKEN and CHAT
    store = family.store
    tester = store.create_member(SYSTEM, "Live tester", Role.MEMBER)
    tester = store.redeem_invite(store.create_invite(SYSTEM, tester.id), int(CHAT))
    channel = TelegramChannel.from_token(Secret(TOKEN), store, None, poll_timeout=0)
    await channel.start()
    try:
        message_id = await channel.send_text(
            tester,
            "Themi live smoke test: this message has one button and gets edited.",
            [Button("Fine", "smoke", {"n": 1})],
        )
        assert message_id > 0
        await channel.edit_text(tester, message_id, "Themi live smoke test: edited. All good.")
        await channel.poll_once()  # the long-poll path works (whatever it finds)
    finally:
        await channel.stop()
