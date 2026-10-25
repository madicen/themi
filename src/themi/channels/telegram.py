"""Telegram, in long-polling mode, through python-telegram-bot's `Bot`.

Themi runs its own polling loop rather than PTB's `Application` so the update
offset is stored in the database: after a restart nothing is processed twice.
An update counts as handled once the handler returns (or fails; a failing
update is logged and skipped, never retried forever).

Who may talk to the bot:
- A paired member: their Telegram user id is on their member record.
- Anyone sending `/start <invite code>`: the pairing attempt. Five wrong
  codes in an hour and that account is ignored for the rest of the hour.
- Everyone else is ignored. Only their Telegram user id is logged, never
  what they wrote.

Only private chats are handled for now; the family group arrives in Phase 2.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import secrets
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from typing import Any

# Opt in to PTB's timedelta time periods now (they become the default in a
# future major version); `_seconds` handles both forms either way.
os.environ.setdefault("PTB_TIMEDELTA", "1")

import telegram
from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageReactionUpdated,
    ReactionTypeEmoji,
    Update,
)
from telegram.constants import ChatAction, ChatType
from telegram.error import Conflict, NetworkError, RetryAfter, TelegramError
from telegram.request import HTTPXRequest

from themi import clock
from themi.accounts import AccountStore, InviteError, Member
from themi.channels.events import (
    Button,
    ButtonPress,
    InboundEvent,
    InboundHandler,
    Reaction,
    VoiceNote,
)
from themi.logs import quiet_chatty_libraries
from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

ALLOWED_UPDATES = ["message", "callback_query", "message_reaction"]
OFFSET_KEY = "telegram.offset"
BUTTON_TTL = timedelta(days=7)
PAIRING_FAILURE_LIMIT = 5
PAIRING_WINDOW = timedelta(hours=1)
TYPING_REFRESH_SECONDS = 4.5  # Telegram shows "typing" for about 5 s per action
MAX_VOICE_BYTES = 20 * 1024 * 1024  # bots can't download larger files anyway

PAIRED_TEXT = "Hi {name}! This chat is now connected to Themi."
ALREADY_PAIRED_TEXT = "You're already connected. Nothing more to set up here."
BAD_CODE_TEXT = "That code didn't work. An admin can make a fresh one with `themi invite`."
NOT_YOURS_TEXT = "That one isn't yours to answer."
ALREADY_HANDLED_TEXT = "Already taken care of."


class TelegramChannel:
    def __init__(
        self,
        bot: telegram.Bot,
        store: AccountStore,
        handler: InboundHandler | None,
        *,
        poll_timeout: int = 30,
        sleep: Any = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.bot = bot
        self.store = store
        self.handler = handler
        self.poll_timeout = poll_timeout
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._pairing_failures: dict[int, list[datetime]] = {}
        # PTB logs whole updates (what people write) at DEBUG, and httpx logs
        # request URLs, which contain the bot token, at INFO.
        quiet_chatty_libraries()

    @classmethod
    def from_token(
        cls,
        token: Secret,
        store: AccountStore,
        handler: InboundHandler | None,
        *,
        base_url: str | None = None,
        base_file_url: str | None = None,
        poll_timeout: int = 30,
        **kwargs: Any,
    ) -> TelegramChannel:
        options: dict[str, Any] = {}
        if base_url:
            options["base_url"] = base_url
        if base_file_url:
            options["base_file_url"] = base_file_url
        bot = telegram.Bot(
            token.reveal(),
            request=HTTPXRequest(read_timeout=20),
            # Long polls hold the connection open for up to poll_timeout seconds.
            get_updates_request=HTTPXRequest(read_timeout=poll_timeout + 10),
            **options,
        )
        return cls(bot, store, handler, poll_timeout=poll_timeout, **kwargs)

    # ----- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        await self.bot.initialize()
        # Polling and webhooks are exclusive; make sure no webhook is left over.
        await self.bot.delete_webhook(drop_pending_updates=False)

    async def stop(self) -> None:
        await self.bot.shutdown()

    async def run(self, stop: asyncio.Event | None = None) -> None:
        """Poll until `stop` is set, backing off after errors."""
        stop = stop or asyncio.Event()
        failures = 0
        while not stop.is_set():
            try:
                await self.poll_once()
                failures = 0
            except RetryAfter as exc:
                await self._sleep(_seconds(exc))
            except (NetworkError, Conflict) as exc:
                # Conflict: another poller is using this token (e.g. an old instance).
                failures += 1
                wait = self._rng.uniform(0, min(60.0, 2.0**failures))
                log.warning(
                    "Telegram polling failed (%s); retrying in %.1fs", type(exc).__name__, wait
                )
                await self._sleep(wait)

    async def poll_once(self) -> int:
        """Fetch and handle one batch of updates. Returns how many were handled."""
        offset = self._offset()
        updates = await self.bot.get_updates(
            offset=offset, timeout=self.poll_timeout, allowed_updates=ALLOWED_UPDATES
        )
        for update in updates:
            if offset is not None and update.update_id < offset:
                continue
            try:
                await self._process(update)
            except Exception:
                log.exception("Failed handling Telegram update %s; skipping it", update.update_id)
            self._save_offset(update.update_id + 1)
        return len(updates)

    def _offset(self) -> int | None:
        row = self.store.db.one("SELECT value FROM meta WHERE key = ?", (OFFSET_KEY,))
        return int(row["value"]) if row else None

    def _save_offset(self, offset: int) -> None:
        self.store.db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (OFFSET_KEY, str(offset)),
        )

    # ----- inbound ------------------------------------------------------------

    async def _process(self, update: Update) -> None:
        if update.message is not None:
            await self._on_message(update.update_id, update.message)
        elif update.callback_query is not None:
            await self._on_button(update.update_id, update.callback_query)
        elif update.message_reaction is not None:
            await self._on_reaction(update.update_id, update.message_reaction)

    async def _on_message(self, update_id: int, message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        if message.chat.type != ChatType.PRIVATE:
            log.info("Ignoring a %s chat message (chat %s)", message.chat.type, message.chat.id)
            return
        text = message.text or ""
        if text.startswith("/start"):
            await self._pair(user.id, message.chat.id, text.removeprefix("/start").strip())
            return
        member = self.store.member_by_telegram(user.id)
        if member is None:
            log.info("Ignoring a message from unknown Telegram user %s", user.id)
            return

        voice = await self._download_voice(message)
        if voice is not None:
            self.store.log_message(member.id, "in", "[voice note]", "voice", message.message_id)
            event = InboundEvent(
                "voice",
                member,
                message.chat.id,
                message.message_id,
                clock.now(),
                update_id,
                voice=voice,
            )
        elif text:
            self.store.log_message(member.id, "in", text, "chat", message.message_id)
            event = InboundEvent(
                "text",
                member,
                message.chat.id,
                message.message_id,
                clock.now(),
                update_id,
                text=text,
            )
        else:
            return  # stickers, photos and the like aren't handled yet
        await self._dispatch(event)

    async def _dispatch(self, event: InboundEvent) -> None:
        if self.handler is None:
            raise RuntimeError("TelegramChannel.handler must be set before polling")
        await self.handler.handle(event, self)

    async def _download_voice(self, message: Message) -> VoiceNote | None:
        media = message.voice or message.audio
        if media is None:
            return None
        if media.file_size and media.file_size > MAX_VOICE_BYTES:
            log.info("Skipping a %d-byte voice note (too large)", media.file_size)
            return None
        file = await self.bot.get_file(media.file_id)
        data = bytes(await file.download_as_bytearray())
        return VoiceNote(data, media.mime_type or "audio/ogg", int(_seconds(media.duration)))

    async def _pair(self, telegram_user_id: int, chat_id: int, code: str) -> None:
        existing = self.store.member_by_telegram(telegram_user_id)
        if existing is not None:
            await self._send_raw(existing, chat_id, ALREADY_PAIRED_TEXT, kind="system")
            return
        if self._pairing_blocked(telegram_user_id):
            log.info(
                "Ignoring pairing attempt from rate-limited Telegram user %s", telegram_user_id
            )
            return
        try:
            member = self.store.redeem_invite(code, telegram_user_id) if code else None
        except InviteError:
            member = None
        if member is None:
            self._pairing_failures.setdefault(telegram_user_id, []).append(clock.now())
            log.info("Failed pairing attempt from Telegram user %s", telegram_user_id)
            await self.bot.send_message(chat_id, BAD_CODE_TEXT)
            return
        log.info("Paired Telegram user %s with member %s", telegram_user_id, member.id)
        await self._send_raw(member, chat_id, PAIRED_TEXT.format(name=member.name), kind="system")

    def _pairing_blocked(self, telegram_user_id: int) -> bool:
        cutoff = clock.now() - PAIRING_WINDOW
        recent = [t for t in self._pairing_failures.get(telegram_user_id, []) if t > cutoff]
        self._pairing_failures[telegram_user_id] = recent
        return len(recent) >= PAIRING_FAILURE_LIMIT

    async def _on_button(self, update_id: int, query: CallbackQuery) -> None:
        member = self.store.member_by_telegram(query.from_user.id)
        if member is None:
            log.info("Ignoring a button tap from unknown Telegram user %s", query.from_user.id)
            await self._answer(query)
            return
        row = self.store.db.one("SELECT * FROM callback_tokens WHERE token = ?", (query.data,))
        if row is None or row["member_id"] != member.id:
            await self._answer(query, NOT_YOURS_TEXT if row else ALREADY_HANDLED_TEXT)
            return
        if row["used_at"] is not None or datetime.fromisoformat(row["expires_at"]) <= clock.now():
            await self._answer(query, ALREADY_HANDLED_TEXT)
            return
        # One answer per keyboard: the other buttons on it stop working too.
        self.store.db.execute(
            "UPDATE callback_tokens SET used_at = ? WHERE group_id = ? AND used_at IS NULL",
            (clock.now().isoformat(), row["group_id"]),
        )
        await self._answer(query)
        message_id = query.message.message_id if query.message is not None else row["message_id"]
        self.store.log_message(member.id, "in", f"[tapped: {row['label']}]", "button", message_id)
        press = ButtonPress(row["label"], row["kind"], json.loads(row["payload"]), message_id)
        chat_id = query.message.chat.id if query.message is not None else member.telegram_user_id
        event = InboundEvent(
            "button", member, chat_id or 0, message_id, clock.now(), update_id, button=press
        )
        await self._dispatch(event)

    async def _answer(self, query: CallbackQuery, text: str | None = None) -> None:
        # Always answer, or the button keeps spinning on the person's phone.
        with suppress(TelegramError):
            await self.bot.answer_callback_query(query.id, text=text)

    async def _on_reaction(self, update_id: int, reaction: MessageReactionUpdated) -> None:
        if reaction.user is None or reaction.chat.type != ChatType.PRIVATE:
            return
        member = self.store.member_by_telegram(reaction.user.id)
        if member is None:
            return
        before = {_emoji(r) for r in reaction.old_reaction}
        added = tuple(e for r in reaction.new_reaction if (e := _emoji(r)) and e not in before)
        if not added:
            return
        self.store.log_message(
            member.id, "in", f"[reacted {' '.join(added)}]", "reaction", reaction.message_id
        )
        event = InboundEvent(
            "reaction",
            member,
            reaction.chat.id,
            reaction.message_id,
            clock.now(),
            update_id,
            reaction=Reaction(added, reaction.message_id),
        )
        await self._dispatch(event)

    # ----- outbound -----------------------------------------------------------

    async def send_text(
        self, member: Member, text: str, buttons: Sequence[Button] = (), *, kind: str = "chat"
    ) -> int:
        """Send a message (with up to a few buttons on one row). Returns its message id."""
        chat_id = _chat_id(member)
        return await self._send_raw(member, chat_id, text, buttons, kind=kind)

    async def _send_raw(
        self,
        member: Member,
        chat_id: int,
        text: str,
        buttons: Sequence[Button] = (),
        *,
        kind: str = "chat",
    ) -> int:
        group_id, markup = self._keyboard(member, buttons)
        sent = await self._with_flood_retry(
            lambda: self.bot.send_message(chat_id, text, reply_markup=markup)
        )
        if group_id is not None:
            self.store.db.execute(
                "UPDATE callback_tokens SET message_id = ? WHERE group_id = ?",
                (sent.message_id, group_id),
            )
        self.store.log_message(member.id, "out", text, kind, sent.message_id)
        return sent.message_id

    async def edit_text(
        self, member: Member, message_id: int, text: str, buttons: Sequence[Button] = ()
    ) -> None:
        """Replace a message's text (and buttons; none given removes them)."""
        group_id, markup = self._keyboard(member, buttons)
        await self._with_flood_retry(
            lambda: self.bot.edit_message_text(
                text, chat_id=_chat_id(member), message_id=message_id, reply_markup=markup
            )
        )
        if group_id is not None:
            self.store.db.execute(
                "UPDATE callback_tokens SET message_id = ? WHERE group_id = ?",
                (message_id, group_id),
            )
        self.store.log_message(member.id, "out", text, "edit", message_id)

    async def react(self, member: Member, message_id: int, emoji: str) -> None:
        await self._with_flood_retry(
            lambda: self.bot.set_message_reaction(
                _chat_id(member), message_id, reaction=[ReactionTypeEmoji(emoji)]
            )
        )

    @asynccontextmanager
    async def typing(self, member: Member) -> AsyncIterator[None]:
        """Show "typing…" for as long as the block runs."""
        chat_id = _chat_id(member)

        async def show() -> None:
            with suppress(TelegramError):
                await self.bot.send_chat_action(chat_id, ChatAction.TYPING)

        async def keep_typing() -> None:
            while True:
                await asyncio.sleep(TYPING_REFRESH_SECONDS)
                await show()

        await show()  # right away, not after the first refresh interval
        task = asyncio.create_task(keep_typing())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def _keyboard(
        self, member: Member, buttons: Sequence[Button]
    ) -> tuple[str | None, InlineKeyboardMarkup | None]:
        if not buttons:
            return None, None
        group_id = secrets.token_urlsafe(9)
        now = clock.now()
        row = []
        for button in buttons:
            token = secrets.token_urlsafe(12)  # Telegram allows 64 bytes of callback data
            self.store.db.execute(
                "INSERT INTO callback_tokens (token, group_id, member_id, label, kind, payload, "
                "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    token,
                    group_id,
                    member.id,
                    button.label,
                    button.kind,
                    json.dumps(button.payload),
                    now.isoformat(),
                    (now + BUTTON_TTL).isoformat(),
                ),
            )
            row.append(InlineKeyboardButton(button.label, callback_data=token))
        return group_id, InlineKeyboardMarkup([row])

    async def _with_flood_retry(self, call: Any, attempts: int = 3) -> Any:
        for attempt in range(attempts):
            try:
                return await call()
            except RetryAfter as exc:
                if attempt == attempts - 1:
                    raise
                await self._sleep(_seconds(exc))
            except NetworkError:
                if attempt == attempts - 1:
                    raise
                await self._sleep(self._rng.uniform(0, 2.0**attempt))
        raise AssertionError("unreachable")  # pragma: no cover


def _chat_id(member: Member) -> int:
    if member.telegram_user_id is None:
        raise ValueError(f"{member.name} hasn't paired with Telegram yet")
    return member.telegram_user_id  # private chat id == user id


def _emoji(reaction: Any) -> str:
    return getattr(reaction, "emoji", "") or ""


def _seconds(value: Any) -> float:
    """PTB time periods are ints or timedeltas depending on version and settings."""
    if isinstance(value, RetryAfter):
        value = getattr(value, "_retry_after", None) or value.retry_after
    if isinstance(value, timedelta):
        return value.total_seconds()
    return float(value or 0)
