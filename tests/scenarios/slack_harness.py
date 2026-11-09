"""SL5: run a Themi whose only chat is Slack, end to end, and drive it like a person would.

The whole app is built with `build_app` from the given modules, its Slack module pointed at
the fake Slack; scripted models answer, and the clock starts frozen at the harness's START.

    async def test_hello(slack_work):
        slack_work.primary.queue_text("Hi Michael!")
        assert await slack_work.say("hello") == ["Hi Michael!"]
"""

from __future__ import annotations

import asyncio

from tests.fakes.slack_api import APP_TOKEN, BOT_TOKEN, MICHAEL, USER_TOKEN, FakeSlack
from tests.fakes.wiring import connector_options
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import START, ModelBank
from themi import clock
from themi.accounts import Member
from themi.ai.settings import AITask, RouteEntry
from themi.app import App, build_app
from themi.channels.slack import SlackChannel
from themi.config import Template
from themi.core import keys
from themi.modules import Module
from themi.standard.slack import SlackModule
from themi.storage.secrets import Secret


async def _no_sleep(seconds: float) -> None:
    return None


def on_the_fake(
    modules: list[Module], slack: FakeSlack, *, status_sync: bool = False
) -> list[Module]:
    """The modules, with Slack's pointed at the fake (and its tokens the fake's; the user
    token too with `status_sync`)."""
    fake = SlackModule(
        Secret(BOT_TOKEN),
        Secret(APP_TOKEN),
        user_token=Secret(USER_TOKEN) if status_sync else None,
        base_url=slack.base_url,
    )
    return [fake if m.name == "slack" else m for m in modules]


class SlackScenario:
    def __init__(
        self,
        family: SeededFamily,
        slack: FakeSlack,
        modules: list[Module],
        template: Template | None = None,
        user: str = MICHAEL,
        *,
        status_sync: bool = False,
    ) -> None:
        self.family = family
        self.slack = slack
        self.user = user
        self.models = ModelBank()
        self.app: App = build_app(
            family.db,
            family.store.cipher,
            None,
            provider_factory=self.models,
            sleep=_no_sleep,
            modules=on_the_fake(modules, slack, status_sync=status_sync),
            template=template,
            **connector_options(timezone=family.family.timezone),
        )
        self.app.services.site_url = "http://themi.test"
        self.channel = self.app.services.get(SlackChannel)
        self.channel._sleep = _no_sleep  # type: ignore[assignment]  # never a real wait

    def use_scripted_models(self, member: Member) -> None:
        ai = self.app.ai_settings
        primary = ai.add_backend(member, member.id, "Primary", "ollama", model="primary")
        fallback = ai.add_backend(member, member.id, "Fallback", "ollama", model="fallback")
        for task in AITask:
            ai.set_chain(member, member.id, task, [RouteEntry(primary.id), RouteEntry(fallback.id)])

    @property
    def primary(self):  # the scripted provider
        return self.models["primary"]

    async def start(self) -> None:
        clock.freeze(START)
        await self.app.channel.start()
        await self.app.channel.publish_commands(self.app.services.command_menu())

    async def stop(self) -> None:
        await self.app.channel.stop()

    # ----- acting like a person -----------------------------------------------------------

    async def _collect(self, envelope: dict) -> list[str]:
        before = len(self.slack.posts(self.user))
        await self.channel.dispatch(envelope)
        if self.app.services.maybe(keys.conversation) is not None:
            await self.app.services.get(keys.conversation).sidecar.drain()
        await asyncio.sleep(0)
        return self.slack.texts(self.user)[before:]

    async def say(self, text: str, thread_ts: str | None = None) -> list[str]:
        """Write to Themi in the DM (in a thread with `thread_ts`); Themi's replies."""
        return await self._collect(self.slack.dm(self.user, text, thread_ts=thread_ts))

    async def command(self, words: str) -> list[str]:
        """`/themi <words>`; Themi's replies."""
        return await self._collect(self.slack.slash(self.user, words))

    async def tap(self, label: str) -> list[str]:
        """Tap the latest button with this label."""
        for params in reversed(self.slack.posts(self.user)):
            for button in self.slack.buttons(params):
                if button["text"]["text"] == label and button.get("value"):
                    message_id = self.app.db.scalar(
                        "SELECT message_id FROM callback_tokens WHERE token = ?",
                        (button["value"],),
                    )
                    _, ts = self.channel.where(int(message_id)) or ("", "")
                    return await self._collect(self.slack.tap(self.user, button["value"], ts))
        raise AssertionError(f"no {label!r} button was sent")

    async def advance(self, *, hours: float = 0, minutes: float = 0) -> list[str]:
        """Let time pass and deliver whatever became due; what was posted meanwhile."""
        from datetime import timedelta

        before = len(self.slack.posts(self.user))
        clock.advance(timedelta(hours=hours, minutes=minutes))
        await self.app.outbox.flush()
        return self.slack.texts(self.user)[before:]

    def inbox(self) -> list[str]:
        return self.slack.texts(self.user)

    def last_buttons(self) -> list[str]:
        return [b["text"]["text"] for b in self.slack.last_buttons(self.user)]
