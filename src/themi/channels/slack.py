"""SL1: Slack direct messages, as a channel.

Each person talks to Themi in their own DM with the Themi app. Themi writes there with the
bot token (`chat.postMessage`, `chat.update`); what people write arrives over Socket Mode
(SL2) with the app-level token.

Slack names a message by its conversation and a `ts` string; the outbox and the message log
keep integers, so `slack_messages` gives each Slack message an integer id, both ways.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from themi import clock
from themi.accounts import AccountStore, Member
from themi.channels import slack_blocks
from themi.channels.buttons import note_message, store_tokens
from themi.channels.events import Button, InboundHandler
from themi.channels.slack_api import SLACK_API, SlackApi, Sleep
from themi.localtime import to_utc_iso
from themi.logs import quiet_chatty_libraries
from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

NAME = "slack"


class SlackChannel:
    def __init__(
        self,
        store: AccountStore,
        bot: SlackApi,
        app: SlackApi | None = None,
        *,
        pair_by_email: bool = True,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.store = store
        self.db = store.db
        self.bot = bot
        self.app = app  # the app-level token's client, for Socket Mode
        self.pair_by_email = pair_by_email
        self.handler: InboundHandler | None = None
        self.last_poll_at: datetime | None = None  # when the socket last brought anything
        self.bot_user_id = ""  # Themi's own Slack user (auth.test)
        self._sleep = sleep
        self._rng = rng or random.Random()
        quiet_chatty_libraries()  # httpx logs every request at INFO

    @classmethod
    def from_tokens(
        cls,
        store: AccountStore,
        bot_token: Secret,
        app_token: Secret | None,
        *,
        base_url: str = SLACK_API,
        sleep: Sleep = asyncio.sleep,
        **kwargs: Any,
    ) -> SlackChannel:
        bot = SlackApi(bot_token, base_url=base_url, sleep=sleep)
        app = SlackApi(app_token, base_url=base_url, sleep=sleep) if app_token else None
        return cls(store, bot, app, sleep=sleep, **kwargs)

    # ----- lifecycle --------------------------------------------------------------------

    async def start(self) -> None:
        who = await self.bot.call("auth.test")
        self.bot_user_id = str(who.get("user_id") or "")

    async def stop(self) -> None:
        await self.bot.close()
        if self.app is not None:
            await self.app.close()

    async def run(self, stop: asyncio.Event | None = None) -> None:
        if stop is not None:
            await stop.wait()

    # ----- outbound ---------------------------------------------------------------------

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
        """A message (with buttons) in the member's DM with Themi; its id. Slack has no
        family group, so `chat_id` is ignored."""
        channel = await self._dm(member)
        group_id, tokens = store_tokens(self.db, member, buttons, anyone=anyone)
        params: dict[str, Any] = {
            "channel": channel,
            "text": slack_blocks.fallback(text),
            "blocks": slack_blocks.message_blocks(text, buttons, tokens),
        }
        if not link_preview:
            params["unfurl_links"] = False
            params["unfurl_media"] = False
        sent = await self.bot.call("chat.postMessage", **params)
        message_id = self.message_id(str(sent["channel"]), str(sent["ts"]), member)
        note_message(self.db, group_id, message_id)
        self.store.log_message(member.id, "out", text, kind, message_id)
        return message_id

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
        """Replace a message's text and buttons (none given removes them)."""
        found = self.where(message_id)
        if found is None:
            raise ValueError(f"no Slack message {message_id}")
        channel, ts = found
        group_id, tokens = store_tokens(self.db, member, buttons, anyone=anyone)
        await self.bot.call(
            "chat.update",
            channel=channel,
            ts=ts,
            text=slack_blocks.fallback(text),
            blocks=slack_blocks.message_blocks(text, buttons, tokens),
        )
        note_message(self.db, group_id, message_id)
        self.store.log_message(member.id, "out", text, "edit", message_id)

    @asynccontextmanager
    async def typing(self, member: Member) -> AsyncIterator[None]:
        yield  # Slack shows no typing for bots in a DM; a slow reply gets a word (P2a)

    async def publish_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        pass  # Slack's commands live in the app's manifest: `/themi <command>`

    # ----- ids --------------------------------------------------------------------------

    def message_id(self, channel: str, ts: str, member: Member | None = None) -> int:
        """The integer id for a Slack message, made the first time it's seen."""
        row = self.db.one(
            "SELECT id FROM slack_messages WHERE channel = ? AND ts = ?", (channel, ts)
        )
        if row is not None:
            return int(row["id"])
        return self.db.execute(
            "INSERT INTO slack_messages (channel, ts, member_id, created_at) VALUES (?, ?, ?, ?)",
            (channel, ts, member.id if member else None, to_utc_iso(clock.now())),
        )

    def where(self, message_id: int) -> tuple[str, str] | None:
        """The conversation and `ts` of a message by its integer id."""
        row = self.db.one("SELECT channel, ts FROM slack_messages WHERE id = ?", (message_id,))
        return (str(row["channel"]), str(row["ts"])) if row is not None else None

    async def _dm(self, member: Member) -> str:
        """The member's DM with Themi (opened once, then remembered)."""
        user = self.store.identity(member.id, NAME)
        if user is None:
            raise ValueError(f"{member.name} hasn't paired with Slack yet")
        row = self.db.one(
            "SELECT channel FROM slack_dm_channels WHERE member_id = ? AND user_id = ?",
            (member.id, user),
        )
        if row is not None:
            return str(row["channel"])
        opened = await self.bot.call("conversations.open", users=user)
        channel = str(opened["channel"]["id"])
        self.db.execute(
            "INSERT INTO slack_dm_channels (member_id, user_id, channel) VALUES (?, ?, ?) "
            "ON CONFLICT (member_id) DO UPDATE SET user_id = excluded.user_id, "
            "channel = excluded.channel",
            (member.id, user, channel),
        )
        return channel
