"""Command-line entry point. Subcommands are added by later prompts."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

from themi import __version__
from themi.storage.secrets import generate_key

if TYPE_CHECKING:
    from themi.accounts import AccountStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="themi", description="Themi household assistant")
    parser.add_argument("--version", action="version", version=f"themi {__version__}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "keygen", help="print a new secret key for THEMI_SECRET_KEY (keep it safe and backed up)"
    )
    commands.add_parser("init", help="first-run setup: create the family and its first admin")
    invite = commands.add_parser(
        "invite", help="add a member (or re-issue a code) and print their Telegram invite code"
    )
    invite.add_argument("name")
    invite.add_argument("--admin", action="store_true", help="make the new member an admin")
    commands.add_parser(
        "bot", help="run the Telegram bot on its own (echo mode until the agent exists)"
    )
    return parser


def _store() -> AccountStore:
    # Imported here so `themi keygen` works before any settings exist.
    from themi.accounts import AccountStore
    from themi.settings import Settings
    from themi.storage import open_database

    settings = Settings.load()
    return AccountStore(open_database(settings.db_path), settings.cipher())


def _run_bot() -> None:
    import asyncio

    from themi.accounts import AccountStore
    from themi.channels.events import EchoHandler
    from themi.channels.telegram import TelegramChannel
    from themi.logs import configure_logging
    from themi.settings import Settings, SettingsError
    from themi.storage import open_database

    settings = Settings.load()
    if settings.telegram_bot_token is None:
        raise SettingsError(
            "TELEGRAM_BOT_TOKEN is required to run the bot (get one from @BotFather)"
        )
    configure_logging(settings.log_level)
    store = AccountStore(open_database(settings.db_path), settings.cipher())
    channel = TelegramChannel.from_token(settings.telegram_bot_token, store, EchoHandler())

    async def run() -> None:
        await channel.start()
        print("Themi bot is running (echo mode). Ctrl+C to stop.")
        try:
            await channel.run()
        finally:
            await channel.stop()

    asyncio.run(run())


def _ask(question: str, default: str | None) -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{question}{suffix}: ")


def main(argv: Sequence[str] | None = None) -> int:
    from themi.accounts import AccountsError, Role
    from themi.accounts.setup import pairing_instructions, run_init, run_invite
    from themi.settings import SettingsError

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            print(generate_key())
        elif args.command == "init":
            run_init(_store(), _ask, print)
        elif args.command == "invite":
            role = Role.ADMIN if args.admin else Role.MEMBER
            member, code = run_invite(_store(), args.name, role)
            print(pairing_instructions(member, code))
        elif args.command == "bot":
            _run_bot()
        else:
            parser.print_help()
    except (SettingsError, AccountsError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; nothing was saved.", file=sys.stderr)
        return 1
    return 0
