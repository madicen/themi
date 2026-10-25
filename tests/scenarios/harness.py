"""Run Themi end to end and drive it like a person would.

The whole app is built with `build_app`, exactly as in production, against:
- a seeded family (Erin and her husband, both paired with Telegram),
- the fake Telegram Bot API,
- scripted AI models (`scenario.primary`, `scenario.fallback`),
- a frozen clock starting Wednesday 21 October 2026, 09:00 Pacific.

    async def test_hello(scenario):
        scenario.primary.queue_text("Hi Erin!")
        assert await scenario.say("Erin", "hello") == ["Hi Erin!"]

Every member's chain for every AI task is primary, then fallback.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tests.fakes.scripted_provider import ScriptedProvider
from tests.fakes.telegram_api import BOT_TOKEN, FakeTelegram
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.accounts import Member
from themi.ai import Capabilities, PermanentError
from themi.ai.adapters import AdapterConfig
from themi.ai.settings import AITask, RouteEntry
from themi.app import App, build_app
from themi.channels.telegram import TelegramChannel
from themi.storage.secrets import Secret

START = datetime(2026, 10, 21, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))


async def _no_sleep(seconds: float) -> None:
    return None


class ModelBank:
    """Hands the router one ScriptedProvider per model name."""

    def __init__(self) -> None:
        self.providers: dict[str, ScriptedProvider] = {}

    def __call__(self, config: AdapterConfig) -> ScriptedProvider:
        if config.kind in ("anthropic", "gemini") and config.api_key is None:
            raise PermanentError(f"{config.kind} needs an API key")  # as build_provider would
        return self[config.resolved_model]

    def __getitem__(self, model: str) -> ScriptedProvider:
        if model not in self.providers:
            self.providers[model] = ScriptedProvider(
                name="scripted", model=model, capabilities=Capabilities(audio=True)
            )
        return self.providers[model]


class Scenario:
    def __init__(self, family: SeededFamily, telegram: FakeTelegram) -> None:
        self.family = family
        self.telegram = telegram
        self.models = ModelBank()
        self.app: App = build_app(
            family.db,
            family.store.cipher,
            lambda store: TelegramChannel.from_token(
                Secret(BOT_TOKEN),
                store,
                None,
                base_url=telegram.base_url,
                base_file_url=telegram.base_file_url,
                poll_timeout=0,
                sleep=_no_sleep,
            ),
            provider_factory=self.models,
            sleep=_no_sleep,
        )
        for member in (family.erin, family.husband):
            self.use_scripted_models(member)

    # ----- setup --------------------------------------------------------------

    def use_scripted_models(self, member: Member) -> None:
        ai = self.app.ai_settings
        primary = ai.add_backend(member, member.id, "Primary", "ollama", model="primary")
        fallback = ai.add_backend(member, member.id, "Fallback", "ollama", model="fallback")
        for task in AITask:
            ai.set_chain(member, member.id, task, [RouteEntry(primary.id), RouteEntry(fallback.id)])

    def clear_ai_settings(self, member: Member) -> None:
        """Back to a brand-new member's state (Gemini free tier, no key yet)."""
        for backend in self.app.ai_settings.backends(member.id):
            self.app.ai_settings.remove_backend(member, backend.id)

    async def start(self) -> None:
        clock.freeze(START)
        await self.app.channel.start()

    async def stop(self) -> None:
        await self.app.channel.stop()

    @property
    def primary(self) -> ScriptedProvider:
        return self.models["primary"]

    @property
    def fallback(self) -> ScriptedProvider:
        return self.models["fallback"]

    def member(self, name: str) -> Member:
        member = self.app.store.member_by_name(name)
        assert member is not None and member.telegram_user_id is not None
        return member

    # ----- acting like a person -----------------------------------------------

    async def _collect(self, name: str, act: Callable[[int], object]) -> list[str]:
        chat = self.member(name).telegram_user_id
        assert chat is not None
        before = len(self.telegram.sent_texts(chat))
        act(chat)
        await self.app.channel.poll_once()
        return self.telegram.sent_texts(chat)[before:]

    async def say(self, name: str, text: str) -> list[str]:
        """Send a message as `name`; returns Themi's replies to it."""
        return await self._collect(name, lambda chat: self.telegram.send_text(chat, text))

    async def voice(self, name: str, audio: bytes = b"OggS-voice", seconds: int = 4) -> list[str]:
        return await self._collect(
            name, lambda chat: self.telegram.send_voice(chat, audio, duration=seconds)
        )

    async def tap(self, name: str, label: str) -> list[str]:
        """Tap the most recent button labelled `label` in `name`'s chat."""
        chat = self.member(name).telegram_user_id
        for params in reversed(self.telegram.calls("sendMessage")):
            if int(params["chat_id"]) != chat or not params.get("reply_markup"):
                continue
            for button in params["reply_markup"]["inline_keyboard"][0]:
                if button["text"] == label:
                    token, message_id = button["callback_data"], self._message_id_for(params)
                    return await self._collect(
                        name, lambda c, t=token, m=message_id: self.telegram.tap(c, t, m)
                    )
        raise AssertionError(f"no button {label!r} was sent to {name}")

    def _message_id_for(self, params: dict) -> int:
        row = self.app.db.one(
            "SELECT telegram_message_id FROM message_log WHERE direction = 'out' AND text = ? "
            "ORDER BY id DESC LIMIT 1",
            (params["text"],),
        )
        assert row is not None
        return row["telegram_message_id"]

    async def advance(self, *, hours: float = 0, minutes: float = 0) -> list[str]:
        """Let time pass and deliver whatever became due. Returns all texts sent meanwhile."""
        before = len(self.telegram.calls("sendMessage"))
        clock.advance(timedelta(hours=hours, minutes=minutes))
        await self.app.outbox.flush()
        return [p["text"] for p in self.telegram.calls("sendMessage")[before:]]

    # ----- looking ------------------------------------------------------------

    def inbox(self, name: str) -> list[str]:
        """Everything Themi has sent `name` so far."""
        chat = self.member(name).telegram_user_id
        assert chat is not None
        return self.telegram.sent_texts(chat)

    def typing_shown(self, name: str) -> bool:
        chat = self.member(name).telegram_user_id
        return any(int(p["chat_id"]) == chat for p in self.telegram.calls("sendChatAction"))
