"""Command-line entry point. Subcommands are added by later prompts."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from themi import __version__
from themi.storage.secrets import generate_key

if TYPE_CHECKING:
    from themi.accounts import AccountStore
    from themi.backup import Backups
    from themi.runtime import Runtime
    from themi.settings import Settings


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
    commands.add_parser("run", help="run Themi: Telegram bot, scheduler and website")
    login = commands.add_parser(
        "login-link", help="print a one-time website sign-in link for a member (10 minutes)"
    )
    login.add_argument("name")
    feedback = commands.add_parser(
        "feedback", help="print new /bug and /idea reports from the chat, to paste into Claude"
    )
    feedback.add_argument("--all", action="store_true", help="include reviewed reports")
    feedback.add_argument(
        "--done", type=int, nargs="+", metavar="ID", help="mark these reports reviewed"
    )
    backup = commands.add_parser(
        "backup", help="take an encrypted backup now (or --list the ones in storage)"
    )
    backup.add_argument("--list", action="store_true", help="list snapshots instead")
    restore = commands.add_parser(
        "restore", help="restore the database from a snapshot (stop Themi first)"
    )
    restore.add_argument("snapshot", help="a snapshot name from `themi backup --list`, or latest")
    restore.add_argument(
        "--dry-run", action="store_true", help="fetch, decrypt and check it, but change nothing"
    )
    restore.add_argument("--yes", action="store_true", help="really replace the database")
    return parser


def _store() -> AccountStore:
    # Imported here so `themi keygen` works before any settings exist.
    from themi.accounts import AccountStore
    from themi.settings import Settings
    from themi.storage import open_database

    settings = Settings.load()
    return AccountStore(open_database(settings.db_path), settings.cipher())


def build_runtime(settings: Settings, **runtime_options: Any) -> Runtime:
    """Wire Themi from its settings, as `themi run` (and `make dev`) runs it."""
    from themi.app import build_app
    from themi.channels.telegram import TelegramChannel
    from themi.connectors.ourgroceries import OurGroceriesClient
    from themi.runtime import Runtime
    from themi.settings import SettingsError
    from themi.storage import open_database
    from themi.storage.secrets import Secret

    if settings.telegram_enabled and settings.telegram_bot_token is None:
        raise SettingsError("TELEGRAM_BOT_TOKEN is required to run Themi (get one from @BotFather)")
    # With Telegram disabled the channel is never started; sends simply queue.
    token = settings.telegram_bot_token or Secret("0:telegram-disabled")
    api = settings.telegram_api_url  # set only for the simulator
    app = build_app(
        open_database(settings.db_path),
        settings.cipher(),
        lambda store: TelegramChannel.from_token(
            token,
            store,
            None,
            base_url=f"{api}/bot" if api else None,
            base_file_url=f"{api}/file/bot" if api else None,
        ),
        google=settings.google(),
        backup=settings.backup,
        grocery_list=OurGroceriesClient(grocery) if (grocery := settings.ourgroceries()) else None,
    )
    return Runtime(
        app,
        host=settings.http_host,
        port=settings.http_port,
        telegram_enabled=settings.telegram_enabled,
        public_url=settings.public_url,
        **runtime_options,
    )


def _run() -> None:
    import asyncio

    from themi.logs import configure_logging
    from themi.settings import Settings

    settings = Settings.load()
    configure_logging(settings.log_level)
    runtime = build_runtime(settings)

    async def main() -> None:
        runtime.install_signal_handlers()
        await runtime.run()

    asyncio.run(main())


def _login_link(name: str) -> str:
    from themi.accounts import AccountsError
    from themi.settings import Settings
    from themi.web import site_base_url
    from themi.web.auth import WebAuth

    store = _store()
    member = store.member_by_name(name)
    if member is None:
        raise AccountsError(f"there's no member called {name}")
    settings = Settings.load()
    base = site_base_url(settings.public_url, settings.http_host, settings.http_port)
    return f"{base}/login/{WebAuth(store).create_link_token(member)}"


def _backups() -> tuple[Settings, Backups]:
    from themi.backup import Backups
    from themi.settings import Settings, SettingsError

    settings = Settings.load()
    if settings.backup is None:
        raise SettingsError(
            "backups aren't set up: THEMI_BACKUP_ENDPOINT, _BUCKET, _ACCESS_KEY_ID and "
            "_SECRET_ACCESS_KEY (see docs/DEPLOY.md)"
        )
    return settings, Backups(settings.backup, settings.cipher())


def _backup(list_only: bool) -> None:
    import asyncio

    from themi.storage import open_database

    settings, backups = _backups()
    if list_only:
        snapshots = asyncio.run(backups.snapshots())
        for s in snapshots:
            print(f"{s.key}  {s.taken_at.isoformat()}  {s.size:,} bytes")
        keep = settings.backup.keep_days if settings.backup else 30
        print(f"{len(snapshots)} snapshot(s); kept for {keep} days.")
        return
    from themi.accounts import AccountStore
    from themi.backup.job import BackupJob

    store = AccountStore(open_database(settings.db_path), settings.cipher())
    # A by-hand run reports here, not in Telegram.
    result = asyncio.run(BackupJob(store, backups, None).backup_now())
    print(f"Backup {result}.")
    if result == "failed":
        raise SystemExit("The backup failed; the log above says why.")


def _restore(name: str, dry_run: bool, yes: bool) -> None:
    import asyncio
    from pathlib import Path

    settings, backups = _backups()
    if not dry_run and not yes:
        raise SystemExit(
            "Restoring replaces the database (the current one is kept beside it). Stop Themi "
            "first, then run again with --yes, or use --dry-run to only check the snapshot."
        )
    report = asyncio.run(backups.restore(name, Path(settings.db_path), dry_run=dry_run))
    counts = ", ".join(f"{n} {t}" for t, n in report.counts.items())
    print(f"Snapshot {report.snapshot.key} from {report.snapshot.taken_at.isoformat()}")
    print(f"  integrity: {report.integrity}; schema {report.schema_version}; {counts}")
    if dry_run:
        print("Dry run: nothing was changed.")
        return
    print(f"Restored to {report.restored_to}.")
    if report.previous_moved_to:
        print(f"The previous database is kept at {report.previous_moved_to}.")
    print("Start Themi again; any newer migrations run on startup.")


def _bot_username() -> str | None:
    """The bot's username (Telegram's getMe), for tap-to-start invite links.
    None without a token, or if Telegram can't be reached: the code still works."""
    import httpx

    from themi.settings import Settings

    settings = Settings.load()
    if settings.telegram_bot_token is None:
        return None
    base = settings.telegram_api_url or "https://api.telegram.org"
    try:
        response = httpx.get(f"{base}/bot{settings.telegram_bot_token.reveal()}/getMe", timeout=5)
        return str(response.json()["result"]["username"])
    except Exception:  # never show the request: its URL holds the token
        return None


def _feedback(include_reviewed: bool, done: list[int] | None) -> None:
    from themi.core.feedback import FeedbackBook

    book = FeedbackBook(_store().db)
    if done:
        marked = book.mark_reviewed(done)
        print(f"Marked {marked} of {len(done)} as reviewed.")
        return
    print(book.report(book.items(include_reviewed)), end="")


def _ask(question: str, default: str | None) -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{question}{suffix}: ")


def main(argv: Sequence[str] | None = None) -> int:
    from themi.accounts import AccountsError, Role
    from themi.accounts.setup import pairing_instructions, run_init, run_invite
    from themi.backup import BackupError, S3Error
    from themi.settings import SettingsError
    from themi.storage.secrets import DecryptionError

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            print(generate_key())
        elif args.command == "init":
            run_init(_store(), _ask, print, _bot_username())
        elif args.command == "invite":
            role = Role.ADMIN if args.admin else Role.MEMBER
            member, code = run_invite(_store(), args.name, role)
            print(pairing_instructions(member, code, _bot_username()))
        elif args.command == "run":
            _run()
        elif args.command == "login-link":
            print(_login_link(args.name))
        elif args.command == "feedback":
            _feedback(args.all, args.done)
        elif args.command == "backup":
            _backup(args.list)
        elif args.command == "restore":
            _restore(args.snapshot, args.dry_run, args.yes)
        else:
            parser.print_help()
    except (SettingsError, AccountsError, BackupError, S3Error, DecryptionError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; nothing was saved.", file=sys.stderr)
        return 1
    return 0
