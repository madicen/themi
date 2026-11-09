"""SL1: Slack as a channel module. With it, each person talks to Themi in a direct message
with the Themi app in their Slack workspace; the Modules page asks for the app's tokens.

The app is made from the manifest beside this file (`slack_manifest.yaml`, shown in the
setup guide), installed to the workspace, and connects over Socket Mode: Themi opens the
connection, so it needs no public address.
"""

from __future__ import annotations

from pathlib import Path

from themi.modules import Module, ModuleContext, ModuleSetup
from themi.modules.base import ModuleError
from themi.modules.settings import ModuleSettings, env_field
from themi.storage.secrets import Secret

NAME = "slack"
MANIFEST = Path(__file__).parent / "slack_manifest.yaml"


class SlackSettings(ModuleSettings):
    bot_token: Secret | None = env_field(
        "SLACK_BOT_TOKEN",
        secret=True,
        ask="Bot token (starts xoxb-)",
        help="api.slack.com/apps: your app, OAuth & Permissions, Bot User OAuth Token",
        placeholder="xoxb-...",
    )
    app_token: Secret | None = env_field(
        "SLACK_APP_TOKEN",
        secret=True,
        ask="App-level token (starts xapp-)",
        help="api.slack.com/apps: your app, Basic Information, App-Level Tokens "
        "(scope connections:write)",
        placeholder="xapp-...",
    )
    pair_by_email: bool = env_field(
        "SLACK_PAIR_BY_EMAIL",
        True,
        label="Pair people by their Slack email",
        help="Someone whose Slack email is their email in Themi is paired when they first "
        "write; anyone else pairs with a code from the Family page.",
    )


class SlackModule(Module):
    """People's chats with Themi, in Slack direct messages."""

    name = NAME
    title = "Slack"
    summary = "Each person chats with Themi in a Slack direct message."
    cost = "Free (a workspace admin may need to approve the app)"
    kind = "channel"
    settings = SlackSettings
    migrations = Path(__file__).parent / "slack_schema"
    website = "Each person opens Themi under Apps in Slack and says hello."

    def __init__(
        self,
        bot_token: Secret | None = None,
        app_token: Secret | None = None,
        *,
        pair_by_email: bool = True,
        base_url: str | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.app_token = app_token
        self.pair_by_email = pair_by_email
        self.base_url = base_url  # the fake's, in tests

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        s = setup.read(SlackSettings)
        return cls(s.bot_token, s.app_token, pair_by_email=s.pair_by_email)

    def _api(self, token: Secret):
        from themi.channels.slack_api import SLACK_API, SlackApi

        return SlackApi(token, base_url=self.base_url or SLACK_API)

    async def check(self) -> str | None:
        from themi.channels.slack_api import SlackError

        if self.bot_token is None or self.app_token is None:
            return "Slack needs both tokens: the bot token (xoxb-) and the app-level token (xapp-)."
        problems = []
        for token, words, method in (
            (self.bot_token, "The bot token", "auth.test"),
            (self.app_token, "The app-level token", "apps.connections.open"),
        ):
            api = self._api(token)
            try:
                await api.call(method)
            except SlackError as exc:
                problems.append(f"{words} didn't work ({exc.error}).")
            finally:
                await api.close()
        return " ".join(problems) or None

    def install(self, ctx: ModuleContext) -> None:
        if NAME in ctx.services.channels:
            return  # given by the app already (tests)
        if self.bot_token is None or self.app_token is None:
            raise ModuleError("slack needs SLACK_BOT_TOKEN and SLACK_APP_TOKEN (see its guide)")
        from themi.channels.slack import SlackChannel
        from themi.channels.slack_api import SLACK_API

        channel = SlackChannel.from_tokens(
            ctx.services.store,
            self.bot_token,
            self.app_token,
            base_url=self.base_url or SLACK_API,
            pair_by_email=self.pair_by_email,
        )
        ctx.provide(channel)
        ctx.channel(NAME, channel)
