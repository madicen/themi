"""`make dev`: run Themi on this computer against the Telegram simulator.

One process runs the simulator (http://localhost:8090) and `themi run`, wired
exactly as in production but pointed at the simulator. Dev data lives in
`data/dev/` with its own secret key, so it never touches the real database.

The first run seeds the test family (Erin and Husband, both paired) and puts
`GEMINI_API_KEY` from `.env` on each person's default AI backend. Each run
prints a sign-in link for the website.

    python -m tools.dev            # run
    python -m tools.dev invite Sam # a new member's invite code, for the "Someone new" chat
    python -m tools.dev reset      # delete data/dev
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from tests.fakes.telegram_api import BOT_TOKEN
from tests.fixtures.family import ERIN_TELEGRAM_ID, seed_family
from themi.accounts import SYSTEM, AccountStore
from themi.accounts.setup import run_invite
from themi.ai.settings import AISettingsStore
from themi.channels.telegram import OFFSET_KEY
from themi.settings import Settings, read_dotenv
from themi.storage import open_database
from themi.storage.secrets import Secret, generate_key

DEV_DIR = Path("data/dev")
SIMULATOR_PORT = 8090
SCHEDULER_TICK = timedelta(seconds=2)  # skipped-ahead nudges show up quickly


@dataclass(frozen=True)
class SeedResult:
    seeded: bool  # False when the dev family already existed
    key_set: bool


def dev_settings(dev_dir: Path, simulator_url: str, env: Mapping[str, str]) -> Settings:
    """Settings for the dev process. Only the website's port and log level carry over."""
    dev_dir.mkdir(parents=True, exist_ok=True)
    key_file = dev_dir / "secret.key"
    if not key_file.exists():
        key_file.write_text(generate_key() + "\n")
        key_file.chmod(0o600)
    return Settings.from_mapping(
        {
            "THEMI_SECRET_KEY_FILE": str(key_file),
            "THEMI_DB_PATH": str(dev_dir / "themi.db"),
            "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
            "TELEGRAM_API_URL": simulator_url,
            "THEMI_HTTP_HOST": "127.0.0.1",
            "THEMI_HTTP_PORT": env.get("THEMI_HTTP_PORT", "8080"),
            "THEMI_LOG_LEVEL": env.get("THEMI_LOG_LEVEL", "INFO"),
        }
    )


def _store(settings: Settings) -> AccountStore:
    return AccountStore(open_database(settings.db_path), settings.cipher())


def seed(settings: Settings, gemini_key: str) -> SeedResult:
    """Ready the dev data for a run: the test family (made once, with the Gemini key on
    everyone's default backend), and no Telegram offset from the last run."""
    store = _store(settings)
    try:
        # Each run's simulator numbers updates from 1, so an offset stored by the last
        # run would make Themi skip that many messages.
        store.db.execute("DELETE FROM meta WHERE key = ?", (OFFSET_KEY,))
        if store.get_family() is not None:
            return SeedResult(seeded=False, key_set=_has_key(store, settings))
        family = seed_family(store)
        ai = AISettingsStore(store.db, store.cipher)
        for member in (family.erin, family.husband):
            ai.ensure_defaults(member.id)
            if gemini_key:
                for backend in ai.backends(member.id):
                    ai.update_backend(SYSTEM, backend.id, api_key=Secret(gemini_key))
        return SeedResult(seeded=True, key_set=bool(gemini_key))
    finally:
        store.db.close()


def _has_key(store: AccountStore, settings: Settings) -> bool:
    ai = AISettingsStore(store.db, settings.cipher())
    return any(b.has_key for m in store.list_members() for b in ai.backends(m.id))


def login_link(settings: Settings, telegram_user_id: int = ERIN_TELEGRAM_ID) -> str | None:
    """A website sign-in link (valid 10 minutes) for whoever uses that Telegram account."""
    from themi.web import site_base_url
    from themi.web.auth import WebAuth

    store = _store(settings)
    try:
        member = store.member_by_telegram(telegram_user_id)
        if member is None:
            return None
        base = site_base_url(settings.public_url, settings.http_host, settings.http_port)
        return f"{base}/login/{WebAuth(store).create_link_token(member)}"
    finally:
        store.db.close()


def invite(settings: Settings, name: str) -> str:
    store = _store(settings)
    try:
        if store.get_family() is None:
            raise SystemExit("There's no dev family yet; run make dev first.")
        _, code = run_invite(store, name)
        return code
    finally:
        store.db.close()


def run(dev_dir: Path = DEV_DIR, port: int = SIMULATOR_PORT) -> None:
    from themi.cli import build_runtime
    from themi.logs import configure_logging
    from tools.dev.simulator import Simulator

    env = {**read_dotenv(Path(".env")), **os.environ}
    simulator = Simulator(port)
    simulator.start()
    try:
        settings = dev_settings(dev_dir, simulator.url, env)
        result = seed(settings, env.get("GEMINI_API_KEY", "").strip())
        configure_logging(settings.log_level)
        logging.getLogger().addHandler(simulator.logs)  # for the page's Copy session
        runtime = build_runtime(settings, scheduler_tick=SCHEDULER_TICK)
        simulator.login = lambda telegram_user_id: login_link(settings, telegram_user_id)
        print(_banner(simulator.url, login_link(settings) or "", result, dev_dir), flush=True)

        async def main() -> None:
            runtime.install_signal_handlers()
            await runtime.run()

        asyncio.run(main())
    finally:
        simulator.stop()


def _banner(simulator_url: str, link: str, result: SeedResult, dev_dir: Path) -> str:
    lines = [
        "",
        "Themi is running against the Telegram simulator.",
        f"  Chat:     {simulator_url.replace('127.0.0.1', 'localhost')}",
        f"  Website:  {link}  (Erin; later, use the chat page's Website link)",
        f"  Data:     {dev_dir}/ (make dev-reset starts over)",
    ]
    if result.seeded:
        lines.append("  Seeded Erin and Husband, both paired.")
    if not result.key_set:
        lines.append(
            "  No AI key: put GEMINI_API_KEY in .env and run make dev-reset, or add a key on "
            "the website's AI page. Until then Themi replies that setup is needed."
        )
    lines.append("Ctrl-C stops it.")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.dev", description="Run Themi locally")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("reset", help=f"delete {DEV_DIR}")
    invite_parser = commands.add_parser("invite", help="print an invite code for a new member")
    invite_parser.add_argument("name")
    args = parser.parse_args(argv)
    if args.command == "reset":
        shutil.rmtree(DEV_DIR, ignore_errors=True)
        print(f"Deleted {DEV_DIR}.")
    elif args.command == "invite":
        settings = dev_settings(DEV_DIR, "http://127.0.0.1", os.environ)
        code = invite(settings, args.name)
        print(f'In the simulator, pick "Someone new" and send:  /start {code}')
    else:
        run()
