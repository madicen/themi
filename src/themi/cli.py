"""Command-line entry point. Subcommands are added by later prompts."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themi import __version__
from themi.storage.secrets import generate_key

if TYPE_CHECKING:
    from themi.accounts import AccountStore
    from themi.backup import Backups
    from themi.config import InstanceConfig
    from themi.runtime import Runtime
    from themi.settings import Settings
    from themi.storage.db import Database

log = logging.getLogger(__name__)


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
    config = commands.add_parser("config", help="what this Themi is made of (themi.toml)")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser(
        "show", help="the template, the modules that will load, and their settings sections"
    )
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
    feedback.add_argument(
        "--wrong-tool",
        nargs=2,
        metavar=("REPLY", "TOOL"),
        help="label a reply marked 👎: the tool it should have used, or none",
    )
    feedback.add_argument(
        "--not-wrong", type=int, metavar="REPLY", help="clear a 👎 mark: the reply was right"
    )
    feedback.add_argument(
        "--pictures",
        metavar="FOLDER",
        help="write the listed reports' screenshots to this folder (decrypted)",
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
    cozyla = commands.add_parser("cozyla", help="the Cozyla wall calendar (unofficial API)")
    cozyla_commands = cozyla.add_subparsers(dest="cozyla_command", required=True)
    cozyla_check = cozyla_commands.add_parser(
        "check", help="sign in and show the lists and members, changing nothing"
    )
    cozyla_check.add_argument(
        "--titles", action="store_true", help="also list the open to-dos on COZYLA_TODO_LIST"
    )
    cozyla_check.add_argument(
        "--fields",
        action="store_true",
        help="also print every field of each open to-do on COZYLA_TODO_LIST, in Cozyla's order",
    )
    keep = commands.add_parser(
        "keep", help="Google Keep, for groceries said to Google Home (unofficial API)"
    )
    keep_commands = keep.add_subparsers(dest="keep_command", required=True)
    keep_link = keep_commands.add_parser(
        "link", help="link a member's Google Keep: its shopping list goes on the grocery list"
    )
    keep_link.add_argument("name")
    keep_link.add_argument("--list", default="Shopping list", help="the Keep list to watch")
    keep_unlink = keep_commands.add_parser("unlink", help="forget a member's Google Keep")
    keep_unlink.add_argument("name")
    tuya = commands.add_parser("tuya", help="the SmartLife feeders, through Tuya's cloud")
    tuya_commands = tuya.add_subparsers(dest="tuya_command", required=True)
    tuya_capture = tuya_commands.add_parser(
        "capture",
        help="read each linked Tuya device's data points and save them as test fixtures "
        "(no ids, keys or names), so a mapping can be written for its model",
    )
    tuya_capture.add_argument("--out", default="tuya-captures", help="the folder to write to")
    catgenie = commands.add_parser("catgenie", help="the litter box, through CatGenie's cloud")
    catgenie_commands = catgenie.add_subparsers(dest="catgenie_command", required=True)
    catgenie_capture = catgenie_commands.add_parser(
        "capture",
        help="read what the litter box reports, and the app's notifications, and save them as "
        "a test fixture (no ids, names or numbers), so its errors can be put in words",
    )
    catgenie_capture.add_argument(
        "--out", default="catgenie-captures", help="the folder to write to"
    )
    return parser


def _store() -> AccountStore:
    # Imported here so `themi keygen` works before any settings exist.
    from themi.accounts import AccountStore
    from themi.settings import Settings
    from themi.storage import open_database

    settings = Settings.load()
    return AccountStore(open_database(settings.db_path), settings.cipher())


def build_runtime(
    settings: Settings,
    *,
    connectors: Mapping[str, Any] | None = None,
    config: InstanceConfig | None = None,
    **runtime_options: Any,
) -> Runtime:
    """Wire Themi from its settings, as `themi run` (and `make dev`) runs it.

    The modules come from themi.toml, or the family template (CR5a). `connectors` instead
    gives the family's modules these connectors (`make dev` passes the fakes, D5a)."""
    from themi.app import build_app
    from themi.channels.telegram import TelegramChannel
    from themi.runtime import Runtime
    from themi.settings import SettingsError
    from themi.storage import open_database
    from themi.storage.secrets import Secret

    modules = None
    template = None
    report = None
    options: dict[str, Any] = {}
    from themi.config import load_template, resolve_start
    from themi.modules.store import ModuleSecrets

    # SP1: a module's problem leaves it off and Themi starts; Telegram with no token is
    # one of those, said on the dashboard rather than stopping everything.
    unavailable = {}
    if settings.telegram_enabled and settings.telegram_bot_token is None:
        unavailable["telegram"] = "it needs a bot token (TELEGRAM_BOT_TOKEN, from @BotFather)"
    db = open_database(settings.db_path)
    stored = ModuleSecrets(db, settings.cipher()).all()  # SP2: set on the Modules page
    if connectors is not None and config is None:  # `make dev`: the family, on the fakes
        options = dict(connectors)
    elif connectors is not None and config is not None:  # CR16: any setup, on the fakes
        from themi.app import family_modules

        config = _chat_in_the_simulator(config)
        on_fakes = {m.name: m for m in family_modules(**connectors)}
        modules, report = resolve_start(config, settings, given=on_fakes, unavailable=unavailable)
        template = load_template(config.template)
    else:  # CR5a: the modules themi.toml (or the family template) names
        config = config or _instance_config(settings, db)
        modules, report = resolve_start(config, settings, unavailable=unavailable, stored=stored)
        template = load_template(config.template)
    if config is not None and not settings.public_url and config.core.get("public_url"):
        # SP2: the website's address, as set on the Modules page (the environment wins)
        settings = settings.model_copy(
            update={"public_url": str(config.core["public_url"]).rstrip("/")}
        )
    for line in report.warnings() if report is not None else ():
        log.warning("%s", line)
    # CR20b: Telegram's channel, when the setup has the telegram module (the family's
    # always does). The runner builds it, since only it knows the simulator's address.
    telegram = modules is None or any(m.name == "telegram" for m in modules)
    if telegram and settings.telegram_enabled and settings.telegram_bot_token is None:
        raise SettingsError("TELEGRAM_BOT_TOKEN is required to run Themi (get one from @BotFather)")
    # With Telegram disabled the channel is never started; sends simply queue.
    token = settings.telegram_bot_token or Secret("0:telegram-disabled")
    api = settings.telegram_api_url  # set only for the simulator
    app = build_app(
        db,
        settings.cipher(),
        (
            lambda store: TelegramChannel.from_token(
                token,
                store,
                None,
                base_url=f"{api}/bot" if api else None,
                base_file_url=f"{api}/file/bot" if api else None,
            )
        )
        if telegram
        else None,
        backup=settings.backup,
        tool_routing=settings.tool_routing,
        conversation_mode=settings.conversation_mode,
        control_dir=settings.control_dir,
        modules=modules,
        template=template,
        report=report,
        **options,
    )
    from themi.accounts.claim import CODE_FILE, Claim

    claim = Claim(app.store)
    if claim.needed():  # SP7a: a new Themi, claimed on its website
        code = claim.make(settings.db_path.parent)
        log.warning(
            "Nobody has set up this Themi yet. Open its website and enter the claim code "
            "%s (it's also in %s).",
            code,
            settings.db_path.parent / CODE_FILE,
        )
    app.services.instance_config = config  # SP4: for the Modules page
    app.services.environment = dict(settings.environment)
    app.services.settings = settings
    return Runtime(
        app,
        host=settings.http_host,
        port=settings.http_port,
        telegram_enabled=settings.telegram_enabled,
        public_url=settings.public_url,
        **runtime_options,
    )


def config_report(settings: Settings, env: dict[str, str] | None = None) -> str:
    """`themi config show`: where the config came from, the template, and each module."""
    from themi.config import config_path, load_config, load_template, resolve_start
    from themi.modules.settings import plain_values, read_settings

    path = config_path(env)
    config = load_config(path)
    modules, report = resolve_start(config, settings)  # SP1: what starts, and what doesn't
    template = load_template(config.template)
    lines = [
        f"Config: {path if path else 'none (the family template, from the environment)'}",
        f"Template: {template.name}",
        f"Modules ({len(modules)}):",
        *(f"  {m.name}" for m in modules),
    ]
    left_out = report.lines()
    if left_out:
        lines.append("Left out:")
        lines += left_out
    warnings = report.warnings()
    if warnings:
        lines.append("To look at:")
        lines += [f"  {w}" for w in warnings]
    for module in modules:  # CR5b: each module's settings, secrets left out
        model = type(module).settings
        if model is None:
            continue
        values = plain_values(
            read_settings(
                model, settings.environment, config.sections.get(module.name, {}), module.name
            )
        )
        lines.append(f"[module.{module.name}]")
        lines += [f"  {key} = {value!r}" for key, value in values.items()]
    return "\n".join(lines)


def _run() -> None:
    import asyncio

    from themi.logs import configure_logging
    from themi.settings import Settings, ensure_secret_key, read_dotenv

    made = ensure_secret_key({**read_dotenv(Path(".env")), **os.environ})  # SP2
    settings = Settings.load()
    configure_logging(settings.log_level)
    if made is not None:
        log.warning("Made a new secret key at %s. Save a copy somewhere safe.", made)
    runtime = build_runtime(settings)

    async def main() -> None:
        runtime.install_signal_handlers()
        await runtime.run()

    from themi.runtime import PortInUse

    try:
        asyncio.run(main())
    except PortInUse as exc:
        log.error("%s", exc)
        raise SystemExit(1) from None
    if runtime.restart_requested:  # SP6: asked for on the Modules page
        from themi.runtime import reexec

        log.info("Starting again, with the Modules page's changes")
        reexec()


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


def _feedback(
    include_reviewed: bool,
    done: list[int] | None,
    wrong_tool: list[str] | None = None,
    not_wrong: int | None = None,
    pictures: str | None = None,
) -> int:
    from pathlib import Path

    from themi.core.naming import NamingRefusals
    from themi.core.naming import report as naming_report
    from themi.standard.feedback import FeedbackBook, picture_name
    from themi.standard.wrong_replies import (
        LABEL_WORDS,
        ReplyReview,
        ReviewError,
        report,
        stub_text,
    )

    store = _store()
    book = FeedbackBook(store.db, store.cipher)
    review = ReplyReview(store.db)
    if done:
        marked = book.mark_reviewed(done)
        print(f"Marked {marked} of {len(done)} as reviewed.")
        return 0
    if wrong_tool or not_wrong is not None:
        reply_text, tool = wrong_tool if wrong_tool else (str(not_wrong), None)
        if not reply_text.isdigit():
            print("The reply is a number, as `themi feedback` lists it.", file=sys.stderr)
            return 1
        try:
            reply, stub = review.label(int(reply_text), tool)
        except ReviewError as exc:
            print(exc, file=sys.stderr)
            return 1
        assert reply.label is not None
        print(f"Reply {reply.id}: {LABEL_WORDS[reply.label]}.")
        if stub is not None:
            print("A case for tests/evals/cases.json:")
            print(stub_text(stub))
        return 0
    family = store.get_family()
    items = book.items(include_reviewed)
    if pictures:  # F34o: the screenshots, decrypted, only where they asked
        folder = Path(pictures).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        written = 0
        for item in items:
            for n, kept in enumerate(book.pictures([item.id]), 1):
                (folder / picture_name(item.id, kept, n)).write_bytes(kept.data)
                written += 1
        print(f"Wrote {written} screenshot(s) to {folder}.", file=sys.stderr)
    print(book.report(items), end="")
    marked_report = report(review.unlabelled(), family.timezone if family else "UTC")
    if marked_report:
        print("\n" + marked_report, end="")
    refusals = naming_report(NamingRefusals(store.db).weeks(), family.timezone if family else "UTC")
    if refusals:
        print("\n" + refusals, end="")
    return 0


def _cozyla_check(titles: bool, fields: bool = False) -> int:
    import asyncio

    from themi.modules.settings import SettingsProblem, read_settings
    from themi.settings import Settings
    from themi_cozyla.connector import CozylaClient, CozylaError
    from themi_cozyla.connector.check import check
    from themi_cozyla.settings import CozylaSettings

    settings = Settings.load()
    try:
        config = read_settings(CozylaSettings, settings.environment, {}, "cozyla_todos").config()
    except SettingsProblem as exc:
        print("; ".join(exc.problems), file=sys.stderr)
        return 1
    if config is None:
        print("Set COZYLA_EMAIL and COZYLA_PASSWORD in .env first.", file=sys.stderr)
        return 1
    family = _store().get_family()
    client = CozylaClient(config, timezone=family.timezone if family else "UTC")

    async def run() -> str:
        try:
            return await check(client, titles=titles, fields=fields)
        finally:
            await client.aclose()

    try:
        print(asyncio.run(run()))
    except CozylaError as exc:
        print(f"Cozyla check failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _keep(command: str, name: str, list_name: str) -> int:
    import asyncio
    from getpass import getpass

    from themi.accounts import AccountsError
    from themi_home.connectors.gkeep import GKeepAccount, KeepError, exchange_token
    from themi_home.keep_groceries import KeepLinks, run_keep_link

    store = _store()
    member = store.member_by_name(name)
    if member is None:
        raise AccountsError(f"there's no member called {name}")
    links = KeepLinks(store.db, store.cipher)
    if command == "unlink":
        gone = links.unlink(member)
        print(
            f"Forgot {member.name}'s Google Keep." if gone else f"{member.name} hadn't linked Keep."
        )
        return 0
    try:
        asyncio.run(
            run_keep_link(
                links,
                member,
                list_name,
                lambda q: _ask(q, None),
                lambda q: getpass(f"{q}: "),
                exchange_token,
                GKeepAccount,
                print,
            )
        )
    except KeepError as exc:
        print(f"Keep wasn't linked: {exc}", file=sys.stderr)
        return 1
    return 0


def _tuya_capture(out: str) -> int:
    import asyncio
    from pathlib import Path

    from themi_home.connectors.tuya import TuyaAccount, TuyaConfig, TuyaError, TuyaWatcher
    from themi_home.connectors.tuya.watch import write_captures

    store = _store()
    watcher = TuyaWatcher(store, TuyaAccount(store.db, store.cipher, TuyaConfig()))
    if not watcher.account.linked():
        print("Link Tuya on the website's Accounts page first.", file=sys.stderr)
        return 1
    folder = Path(out)

    async def run() -> list[Path]:
        try:
            return await write_captures(watcher, folder)
        finally:
            await watcher.account.close()

    try:
        written = asyncio.run(run())
    except TuyaError as exc:
        print(f"Tuya capture failed: {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(f"Wrote {path}")
    if not written:
        print("Tuya is linked, but it has no devices.")
    return 0


def _catgenie_capture(out: str) -> int:
    import asyncio
    from pathlib import Path

    from themi_home.connectors.catgenie import (
        CatGenieAccount,
        CatGenieConfig,
        CatGenieError,
        CatGenieWatcher,
    )
    from themi_home.connectors.catgenie.watch import write_captures

    store = _store()
    watcher = CatGenieWatcher(store, CatGenieAccount(store.db, store.cipher, CatGenieConfig()))
    if not watcher.account.linked():
        print("Link the litter box on the website's Accounts page first.", file=sys.stderr)
        return 1

    async def run() -> Path:
        try:
            return await write_captures(watcher, Path(out))
        finally:
            await watcher.account.close()

    try:
        written = asyncio.run(run())
    except CatGenieError as exc:
        print(f"CatGenie capture failed: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {written}")
    return 0


def _ask(question: str, default: str | None) -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{question}{suffix}: ")


def main(argv: Sequence[str] | None = None) -> int:
    from themi.accounts import AccountsError, Role
    from themi.accounts.setup import pairing_instructions, run_init, run_invite
    from themi.backup import BackupError, S3Error
    from themi.settings import Settings, SettingsError
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
        elif args.command == "config":
            print(config_report(Settings.load()))
        elif args.command == "login-link":
            print(_login_link(args.name))
        elif args.command == "feedback":
            return _feedback(args.all, args.done, args.wrong_tool, args.not_wrong, args.pictures)
        elif args.command == "backup":
            _backup(args.list)
        elif args.command == "restore":
            _restore(args.snapshot, args.dry_run, args.yes)
        elif args.command == "cozyla":
            return _cozyla_check(args.titles, args.fields)
        elif args.command == "keep":
            return _keep(args.keep_command, args.name, getattr(args, "list", ""))
        elif args.command == "tuya":
            return _tuya_capture(args.out)
        elif args.command == "catgenie":
            return _catgenie_capture(args.out)
        else:
            parser.print_help()
    except (SettingsError, AccountsError, BackupError, S3Error, DecryptionError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; nothing was saved.", file=sys.stderr)
        return 1
    return 0


def _instance_config(settings: Settings, db: Database) -> InstanceConfig:
    """themi.toml. With none, an install from before the setup portal (it has a family) is
    the family template, as it always was. A new Themi (no family yet) starts with only
    the core and the web chat, and the file is written so it stays that way once claimed:
    the admin builds it up on the Modules page."""
    from themi.config import (
        InstanceConfig,
        beside_database,
        config_path,
        load_config,
        write_config,
    )

    env = settings.environment or None
    path = config_path(env)
    if path is None and db.one("SELECT 1 FROM family WHERE id = 1") is None:
        path = beside_database(env)
        write_config(InstanceConfig(template="empty", added=("web_chat",)), path)
        log.info("A new Themi: it starts with only its core and the web chat (%s)", path)
    return load_config(path)


def _chat_in_the_simulator(config: InstanceConfig) -> InstanceConfig:
    """SL5: on the fakes, people chat through the simulator, which plays Telegram. A setup
    whose chat is Slack (the work template's) chats there instead; Slack has no fake to
    run against outside the tests."""
    from dataclasses import replace

    from themi.config import load_template

    names = (set(load_template(config.template).modules) | set(config.added)) - set(config.removed)
    if "slack" not in names or "telegram" in names:
        return config
    return replace(
        config,
        added=(*(n for n in config.added if n != "slack"), "telegram"),
        removed=(*config.removed, "slack"),
    )
