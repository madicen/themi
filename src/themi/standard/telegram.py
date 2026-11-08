"""CR20b: Telegram as a channel module. With it, people talk to Themi in Telegram (their own
chats, the family group, the Mini App); `themi setup` asks for the bot's token here.

The runner builds the channel (it knows the simulator's address), and the app adds it
before the modules install; built any other way, this module makes it from the token.
"""

from __future__ import annotations

from themi.modules import Module, ModuleContext, ModuleSetup
from themi.modules.base import ModuleError
from themi.modules.settings import ModuleSettings, env_field
from themi.storage.secrets import Secret

NAME = "telegram"


class TelegramSettings(ModuleSettings):
    token: Secret | None = env_field(
        "TELEGRAM_BOT_TOKEN",
        secret=True,
        ask="Telegram bot token (from @BotFather)",
        help="t.me/BotFather: /newbot",
    )


class TelegramModule(Module):
    """People's chats with Themi, in Telegram."""

    name = NAME
    title = "Telegram"
    summary = "Each person chats with Themi in Telegram, on their phone."
    cost = "Free"
    kind = "channel"
    settings = TelegramSettings
    website = "Each person pairs Telegram with the code from the Family page (/family)."

    def __init__(self, token: Secret | None = None) -> None:
        self.token = token

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        return cls(setup.read(TelegramSettings).token)

    def install(self, ctx: ModuleContext) -> None:
        if NAME in ctx.services.channels:
            return  # the runner's, added by the app
        if self.token is None:
            raise ModuleError("telegram needs TELEGRAM_BOT_TOKEN (get one from @BotFather)")
        from themi.channels.telegram import TelegramChannel

        ctx.channel(NAME, TelegramChannel.from_token(self.token, ctx.services.store, None))
