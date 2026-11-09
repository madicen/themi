"""SL1: Slack direct messages, as a channel.

Each person talks to Themi in their own DM with the Themi app. Themi writes there with the
bot token (`chat.postMessage`, `chat.update`); what people write arrives over Socket Mode
(SL2) with the app-level token.

Slack names a message by its conversation and a `ts` string; the outbox and the message log
keep integers, so `slack_messages` gives each Slack message an integer id, both ways.

SL2, receiving: `run` keeps a Socket Mode connection open, acks each envelope the moment it
arrives (Slack wants an answer within 3 seconds; a reply can take longer), and hands it to a
worker that passes envelopes to `dispatch` one at a time, in order. `dispatch` doesn't care
how an envelope came, so the HTTP Events API could feed it too.

Who may talk to Themi:
- A paired member: a `slack` identity holds their Slack user id.
- Someone not paired whose Slack email is a member's email (with `pair_by_email`): paired
  when they first write.
- Someone sending an invite code from the Family page: the pairing attempt. Five wrong
  codes in an hour and that account is ignored for the rest of the hour.
- Everyone else gets one line saying how to pair, and only their user id is logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from themi import clock
from themi.accounts import AccountStore, InviteError, Member
from themi.channels import slack_blocks
from themi.channels.buttons import note_message, store_tokens
from themi.channels.events import Button, InboundEvent, InboundHandler
from themi.channels.slack_api import SLACK_API, SlackApi, SlackError, Sleep
from themi.localtime import to_utc_iso
from themi.logs import quiet_chatty_libraries
from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

NAME = "slack"
SEEN_FOR = timedelta(days=1)  # how long an event id is kept, to drop Slack's repeats
PAIRING_FAILURE_LIMIT = 5
PAIRING_WINDOW = timedelta(hours=1)
CODE = re.compile(r"^[A-Za-z0-9]{4}[- ]?[A-Za-z0-9]{4}$")  # an invite code, typed loosely
# Messages that aren't someone writing to Themi: edits, deletions, joins, bots.
SKIPPED_SUBTYPES = frozenset(
    {"bot_message", "message_changed", "message_deleted", "channel_join", "ekm_access_denied"}
)

PAIRED_TEXT = "Hi {name}! You're connected to Themi here in Slack."
BAD_CODE_TEXT = "That code didn't work. An admin can make a fresh one on the Family page."
NOT_PAIRED_TEXT = (
    "Hi! I'm Themi, an assistant for the people who've set me up. If that's you, send me "
    "the code from the Family page on Themi's website."
)


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
        self._pairing_failures: dict[str, list[datetime]] = {}
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
        """Keep a Socket Mode connection open until `stop` is set, reconnecting when Slack
        asks to or the connection drops (backing off after failures)."""
        stop = stop or asyncio.Event()
        if self.app is None:
            await stop.wait()
            return
        work: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        worker = asyncio.create_task(self._work(work))
        failures = 0
        try:
            while not stop.is_set():
                try:
                    if await self._connection(stop, work):
                        return
                    failures = 0
                except (SlackError, OSError, WebSocketException, TimeoutError) as exc:
                    failures += 1
                    wait = self._rng.uniform(0, min(60.0, 2.0**failures))
                    log.warning("Slack's socket failed (%s); retrying in %.1fs",
                                type(exc).__name__, wait)  # fmt: skip
                    await self._sleep(wait)
        finally:
            await work.put(None)  # what's already acked is handled before stopping
            await worker

    async def _connection(
        self, stop: asyncio.Event, work: asyncio.Queue[dict[str, Any] | None]
    ) -> bool:
        """One connection, until it ends: True when `stop` was set, False to reconnect."""
        assert self.app is not None
        opened = await self.app.call("apps.connections.open")
        async with connect(str(opened["url"]), open_timeout=20) as socket:
            stopped = asyncio.ensure_future(stop.wait())
            try:
                while True:
                    received = asyncio.ensure_future(socket.recv())
                    done, _ = await asyncio.wait(
                        {received, stopped}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if received not in done:
                        received.cancel()
                        with suppress(asyncio.CancelledError, WebSocketException):
                            await received
                        return True
                    message = json.loads(received.result())
                    self.last_poll_at = clock.now()
                    if message.get("type") == "disconnect":
                        log.info("Slack asked for a new connection (%s)", message.get("reason"))
                        return False
                    envelope_id = message.get("envelope_id")
                    if envelope_id:
                        # Kept before the ack: an ack lost to a closing socket only means
                        # Slack sends it again, and the repeat is dropped.
                        await work.put(message)
                        with suppress(WebSocketException):
                            await socket.send(json.dumps({"envelope_id": envelope_id}))
            finally:
                stopped.cancel()

    async def _work(self, work: asyncio.Queue[dict[str, Any] | None]) -> None:
        while (envelope := await work.get()) is not None:
            try:
                await self.dispatch(envelope)
            except Exception:
                log.exception("Failed handling a Slack %s envelope; skipping it",
                              envelope.get("type"))  # fmt: skip

    # ----- inbound ----------------------------------------------------------------------

    async def dispatch(self, envelope: dict[str, Any]) -> None:
        """One Socket Mode envelope (already acked), however it arrived."""
        kind = envelope.get("type")
        payload = envelope.get("payload") or {}
        if kind == "events_api":
            await self._on_event_callback(payload)

    async def _on_event_callback(self, payload: dict[str, Any]) -> None:
        event_id = str(payload.get("event_id") or "")
        if event_id and not self._first_time(event_id):
            log.info("Dropping a repeat of Slack event %s", event_id)
            return
        event = payload.get("event") or {}
        if event.get("type") == "message":
            await self._on_message(event)

    def _first_time(self, event_id: str) -> bool:
        now = clock.now()
        self.db.execute(
            "DELETE FROM slack_seen_events WHERE seen_at < ?", (to_utc_iso(now - SEEN_FOR),)
        )
        if self.db.one("SELECT 1 FROM slack_seen_events WHERE event_id = ?", (event_id,)):
            return False
        self.db.execute(
            "INSERT INTO slack_seen_events (event_id, seen_at) VALUES (?, ?)",
            (event_id, to_utc_iso(now)),
        )
        return True

    async def _on_message(self, event: dict[str, Any]) -> None:
        user = str(event.get("user") or "")
        if (
            event.get("channel_type") != "im"
            or event.get("bot_id")
            or event.get("subtype") in SKIPPED_SUBTYPES
            or not user
            or user == self.bot_user_id
        ):
            return
        channel, ts = str(event["channel"]), str(event["ts"])
        member = self.store.member_by_identity(NAME, user)
        if member is None:
            await self._pair(user, channel, slack_blocks.plain(str(event.get("text") or "")))
            return
        text = slack_blocks.plain(str(event.get("text") or "")).strip()
        message_id = self.message_id(channel, ts, member)
        if not text:
            return
        self.store.log_message(member.id, "in", text, "chat", message_id)
        await self._hand_on(
            InboundEvent("text", member, member.id, message_id, clock.now(), 0, text=text)
        )

    async def _hand_on(self, event: InboundEvent) -> None:
        if self.handler is None:
            raise RuntimeError("SlackChannel.handler must be set before receiving")
        await self.handler.handle(event, self)

    # ----- pairing ----------------------------------------------------------------------

    async def _pair(self, user: str, channel: str, text: str) -> None:
        if self._pairing_blocked(user):
            log.info("Ignoring Slack user %s (too many wrong codes)", user)
            return
        member = await self._by_email(user) if self.pair_by_email else None
        code = text.strip()
        if member is None and CODE.match(code):
            try:
                member = self.store.redeem_invite(code, user, channel=NAME)
            except InviteError:
                self._pairing_failures.setdefault(user, []).append(clock.now())
                log.info("Failed pairing attempt from Slack user %s", user)
                await self._post(channel, BAD_CODE_TEXT)
                return
        if member is None:
            self._pairing_failures.setdefault(user, []).append(clock.now())
            log.info("Ignoring a message from Slack user %s, who isn't paired", user)
            await self._post(channel, NOT_PAIRED_TEXT)
            return
        log.info("Paired Slack user %s with member %s", user, member.id)
        member = self.store.get_member(member.id)
        sent = await self._post(channel, PAIRED_TEXT.format(name=member.name))
        self.store.log_message(member.id, "out", PAIRED_TEXT.format(name=member.name), "system",
                               self.message_id(channel, sent, member))  # fmt: skip

    async def _by_email(self, user: str) -> Member | None:
        """The member whose email is this Slack user's, paired now; None when there's no
        such member, or they're already on Slack as someone else."""
        try:
            info = await self.bot.call("users.info", user=user)
        except SlackError as exc:
            log.warning("Couldn't look up Slack user %s (%s)", user, exc.error)
            return None
        email = str(((info.get("user") or {}).get("profile") or {}).get("email") or "")
        member = self.store.member_by_email(email) if email else None
        if member is None or self.store.identity(member.id, NAME) not in (None, user):
            return None
        self.store.set_identity(member.id, NAME, user)
        return member

    def _pairing_blocked(self, user: str) -> bool:
        cutoff = clock.now() - PAIRING_WINDOW
        recent = [t for t in self._pairing_failures.get(user, []) if t > cutoff]
        self._pairing_failures[user] = recent
        return len(recent) >= PAIRING_FAILURE_LIMIT

    async def _post(self, channel: str, text: str) -> str:
        """A message straight to a conversation, outside the outbox (pairing, where there
        may be no member yet). Its `ts`."""
        sent = await self.bot.call(
            "chat.postMessage", channel=channel, text=slack_blocks.fallback(text)
        )
        return str(sent["ts"])

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
