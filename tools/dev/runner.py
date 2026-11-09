"""`make dev`: run Themi on this computer against the Telegram simulator.

One process runs the simulator (http://localhost:8090) and `themi run`, wired
exactly as in production but pointed at the simulator. Dev data lives in
`data/dev/` with its own secret key, so it never touches the real database.

The first run seeds the test family (Erin and Husband, both paired) and puts
`GEMINI_API_KEY` from `.env` on each person's default AI backend. Each run
prints a sign-in link for the website.

Every outside service is played by its test fake (tools/dev/fakes.py, D5a), linked on
the first run and kept in `data/dev/fakes.json`. `make dev-prod` runs without them.

    python -m tools.dev            # run, with the fakes for Gmail, the wall, devices... (D5a)
    python -m tools.dev --no-fakes # run with no outside services, as before D5a
    python -m tools.dev invite Sam # a new member's invite code, for the "Someone new" chat
    python -m tools.dev reset      # delete data/dev and data/dev-prod
    python -m tools.dev prod       # a fresh copy of the Pi's data, then run on it (D4)
    python -m tools.dev prod --from-backup latest   # ...from the encrypted backups instead
    python -m tools.dev prod --keep                 # run on the copy already there

CR16: any module setup, on the same fakes, each with its own dev data:

    python -m tools.dev --template work                 # data/dev-work
    python -m tools.dev --modules=-safeway,+travel      # the family's, changed
    python -m tools.dev --config path/to/themi.toml     # data/dev-<the file's name>
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
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from tests.fakes.telegram_api import BOT_TOKEN
from tests.fixtures.family import ERIN_TELEGRAM_ID, seed_family
from themi import clock
from themi.accounts import SYSTEM, AccountStore
from themi.accounts.setup import run_invite
from themi.ai.settings import AISettingsStore
from themi.channels.telegram import OFFSET_KEY
from themi.settings import Settings, read_dotenv
from themi.storage import open_database
from themi.storage.secrets import Secret, generate_key

if TYPE_CHECKING:
    from themi.config import InstanceConfig
    from themi.runtime import Runtime
    from tools.dev.fakes import DevFakes
    from tools.dev.simulator import Simulator

DEV_DIR = Path("data/dev")
PROD_DIR = Path("data/dev-prod")  # D4: a cleaned copy of the family's data (prod_copy)
PI = "themi@themi"  # where `prod` copies from; THEMI_PI changes it
SIMULATOR_PORT = 8090
DEV_HTTP_PORT = "8081"  # the dev website; THEMI_DEV_HTTP_PORT changes it
SCHEDULER_TICK = timedelta(seconds=2)  # skipped-ahead nudges show up quickly


@dataclass(frozen=True)
class SeedResult:
    seeded: bool  # False when the dev family already existed
    key_set: bool


def dev_settings(dev_dir: Path, simulator_url: str, env: Mapping[str, str]) -> Settings:
    """Settings for the dev process. Only THEMI_DEV_HTTP_PORT and the log level carry over."""
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
            # Not THEMI_HTTP_PORT: a real `themi run` on this machine keeps 8080.
            "THEMI_HTTP_PORT": env.get("THEMI_DEV_HTTP_PORT", DEV_HTTP_PORT),
            "THEMI_LOG_LEVEL": env.get("THEMI_LOG_LEVEL", "INFO"),
        }
    )


def _store(settings: Settings) -> AccountStore:
    return AccountStore(open_database(settings.db_path), settings.cipher())


def seed(settings: Settings, gemini_key: str, template: str = "family") -> SeedResult:
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
        store.db.execute("UPDATE family SET template = ?", (template,))  # CR16
        ai = AISettingsStore(store.db, store.cipher)
        for member in (family.erin, family.husband):
            ai.ensure_defaults(member.id)
            if gemini_key:
                for backend in ai.backends(member.id):
                    ai.update_backend(SYSTEM, backend.id, api_key=Secret(gemini_key))
        return SeedResult(seeded=True, key_set=bool(gemini_key))
    finally:
        store.db.close()


def continue_numbering(settings: Settings, simulator: Simulator) -> None:
    """A new simulator would number messages from 100 again; carry on after the dev data's."""
    store = _store(settings)
    try:
        highest = store.db.scalar("SELECT MAX(telegram_message_id) FROM message_log") or 0
    finally:
        store.db.close()
    simulator.number_messages_after(int(highest))


def _has_key_at(settings: Settings) -> bool:
    store = _store(settings)
    try:
        return _has_key(store, settings)
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


def energy_numbers(runtime: Runtime, telegram_user_id: int) -> str:
    """The Shadow Calendar's numbers for the next day, hour by hour (dev only)."""
    from themi.energy.model import EnergyModel

    store = runtime.app.store
    member = store.member_by_telegram(telegram_user_id)
    model = runtime.app.services.energy
    if member is None or not isinstance(model, EnergyModel):
        return "That person isn't a member."
    now = clock.now()
    lines = [f"Energy for {member.name} (dev only; the real app shows words, never these)", ""]
    for hour in range(24):
        moment = now + timedelta(hours=hour)
        lines.append(
            f"{moment.astimezone(ZoneInfo(model.timezone)):%a %H:%M}  "
            f"baseline {model.baseline(member, moment):5.1f}  "
            f"capacity {model.capacity(member, moment):5.1f}"
            + (f"  ({model.label(member)})" if hour == 0 else "")
        )
    lines += ["", "Recent signals:"]
    lines += [f"  {s.at:%a %H:%M} {s.source} {s.value:+.1f}" for s in model.signals(member, now)]
    return "\n".join(lines)


def invite(settings: Settings, name: str) -> str:
    store = _store(settings)
    try:
        if store.get_family() is None:
            raise SystemExit("There's no dev family yet; run make dev first.")
        _, code = run_invite(store, name)
        return code
    finally:
        store.db.close()


@dataclass(frozen=True)
class DevSetup:
    """CR16: which modules this run has, and where its dev data lives."""

    config: InstanceConfig | None  # None: the family's, as before CR16
    name: str  # for the banner and the data folder
    dev_dir: Path


def dev_setup(template: str = "", modules: str = "", config: str = "") -> DevSetup:
    """The setup asked for: a themi.toml, or a template with module changes ("-safeway,+x").
    The family's with no changes runs in data/dev, as before; any other in its own folder."""
    from themi.config import load_config, load_template, parse_config

    if config:
        path = Path(config)
        if not path.exists():
            raise SystemExit(f"There's no {path}.")
        return DevSetup(load_config(path), path.stem, Path(f"data/dev-{_slug(path.stem)}"))
    changes = [c.strip() for c in modules.split(",") if c.strip()]
    if not template and not changes:
        return _from_page(DevSetup(None, "family", DEV_DIR))
    name = template or "family"
    found = parse_config({"template": name, "modules": changes})
    load_template(name)  # an unknown template says so now, before anything starts
    label = name + ("" if not changes else " " + ",".join(changes))
    folder = Path(f"data/dev-{_slug(label)}")
    return _from_page(DevSetup(found, label, folder))


def _from_page(setup: DevSetup) -> DevSetup:
    """SP6: a themi.toml the Modules page wrote into this setup's data folder wins, so a
    restart from the page comes back with its changes."""
    from themi.config import load_config

    written = setup.dev_dir / "themi.toml"
    if not written.exists():
        return setup
    return DevSetup(
        load_config(written), f"{setup.name}, as the Modules page set it", setup.dev_dir
    )


def _slug(text: str) -> str:
    return "".join(
        c if c.isalnum() else "_" for c in text.replace("+", "plus_").replace("-", "minus_")
    )


def run(
    dev_dir: Path = DEV_DIR,
    port: int = SIMULATOR_PORT,
    *,
    copy: bool = False,
    fakes: bool = True,
    setup: DevSetup | None = None,
) -> None:
    """`copy`: dev_dir holds a copy of the family's data (D4), not the seeded test family.
    `fakes`: the outside services are played by the test fakes (D5a; never with `copy`).
    `setup`: the modules to run with and their data folder (CR16); the family's if None."""
    if setup is not None:
        dev_dir = setup.dev_dir
    from themi.cli import build_runtime
    from themi.logs import configure_logging
    from tools.dev.simulator import Simulator

    env = {**read_dotenv(Path(".env")), **os.environ}
    simulator = Simulator(port)
    simulator.start()
    dev_fakes: DevFakes | None = None
    runtime: Runtime | None = None
    try:
        settings = dev_settings(dev_dir, simulator.url, env)
        gemini_key = env.get("GEMINI_API_KEY", "").strip()
        template = setup.config.template if setup and setup.config else "family"
        result = seed(settings, gemini_key, template)
        source = None
        if copy:
            from tools.dev import prod_copy

            source = prod_copy.copied_from(settings)
            keyed = prod_copy.put_dev_key(settings, gemini_key) > 0
            result = SeedResult(seeded=False, key_set=keyed or _has_key_at(settings))
        continue_numbering(settings, simulator)
        configure_logging(settings.log_level)
        logging.getLogger().addHandler(simulator.logs)  # for the page's Copy session
        connectors = None
        if fakes and not copy:
            from tools.dev.fakes import FAKES_FILE, DevFakes

            dev_fakes = DevFakes(dev_dir / FAKES_FILE)
            simulator.controls_coming = True
            dev_fakes.start(site_urls(settings))
            connectors = dev_fakes.connectors(family_timezone(settings))
        runtime = build_runtime(
            settings,
            scheduler_tick=SCHEDULER_TICK,
            connectors=connectors,
            config=setup.config if setup else None,
        )
        simulator.login = lambda telegram_user_id: login_link(settings, telegram_user_id)
        simulator.energy_debug = lambda telegram_user_id: energy_numbers(runtime, telegram_user_id)
        link = login_link(settings) or ""

        async def main() -> None:
            runtime.install_signal_handlers()
            linked = None
            if dev_fakes is not None:
                from tools.dev.controls import ControlPanel

                linked = await dev_fakes.bind(
                    runtime.app, site_urls(settings)[0], runtime.scheduler, runtime.web
                )
                simulator.controls = ControlPanel(dev_fakes)
            modules = [m.name for m in runtime.app.modules]
            label = setup.name if setup else "family"
            print(
                _banner(simulator.url, link, result, dev_dir, source, linked, (label, modules)),
                flush=True,
            )
            await runtime.run()

        asyncio.run(main())
    finally:
        if dev_fakes is not None:
            if dev_fakes.app is not None:
                dev_fakes.save()  # what the fakes got since the last minute's save
            dev_fakes.stop()
        simulator.stop()
    if (
        runtime is not None and runtime.restart_requested
    ):  # SP6: the Modules page's Restart, the whole dev run again
        from themi.runtime import reexec

        print("Starting again, with the Modules page's changes...", flush=True)
        reexec()


def site_urls(settings: Settings) -> list[str]:
    """The dev website's addresses: the one Themi uses for links (localhost) first, then
    127.0.0.1, which reaches the same site."""
    from themi.web import site_base_url

    base = site_base_url(settings.public_url, settings.http_host, settings.http_port)
    return [base, base.replace("localhost", "127.0.0.1")]


def family_timezone(settings: Settings) -> str:
    store = _store(settings)
    try:
        family = store.get_family()
        return family.timezone if family else "America/Los_Angeles"
    finally:
        store.db.close()


def _banner(
    simulator_url: str,
    link: str,
    result: SeedResult,
    dev_dir: Path,
    copy: str | None = None,
    fakes: list[str] | None = None,
    modules: tuple[str, list[str]] | None = None,
) -> str:
    lines = [
        "",
        "Themi is running against the Telegram simulator.",
        f"  Chat:     {simulator_url.replace('127.0.0.1', 'localhost')}",
        f"  Website:  {link}  (Erin; later, use the chat page's Website link)",
        f"  Data:     {dev_dir}/ (make dev-reset starts over)",
    ]
    if modules is not None:  # CR16
        name, loaded = modules
        lines.append(
            f"  Setup:    {name}, {len(loaded)} modules (make dev TEMPLATE=... MODULES=...)"
        )
    if copy:
        lines += [
            f"  A private copy of the family's data ({copy}): their messages and email.",
            "  Member 1 is Erin and member 2 is Husband in the simulator. No links work:",
            "  Gmail, Keep, the wall and the devices aren't reached, and nothing goes to Telegram.",
        ]
    if fakes is not None:
        lines += [
            f"  Controls: {simulator_url.replace('127.0.0.1', 'localhost')}/control "
            "(beside the chat on a wide screen)",
            "  Fakes:    " + "; ".join(fakes),
            f"            kept in {dev_dir}/fakes.json (make dev FAKES=0 runs without them)",
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
    prod_parser = commands.add_parser("prod", help=f"run on a copy of the Pi's data, in {PROD_DIR}")
    prod_parser.add_argument(
        "--from-backup", metavar="NAME", help="a snapshot ('latest', or from `themi backup --list`)"
    )
    prod_parser.add_argument("--keep", action="store_true", help="run on the copy already there")
    parser.add_argument(
        "--no-fakes", action="store_true", help="run without the fakes for outside services"
    )
    parser.add_argument("--template", default="", help="CR16: run another template (work)")
    parser.add_argument(
        "--modules", default="", help='CR16: change its modules, e.g. "-safeway,+travel"'
    )
    parser.add_argument("--config", default="", help="CR16: run the setup a themi.toml names")
    args = parser.parse_args(argv)
    if args.command == "reset":
        others = sorted(Path("data").glob("dev-*")) if Path("data").exists() else []
        for folder in (DEV_DIR, PROD_DIR, *others):
            shutil.rmtree(folder, ignore_errors=True)
        print(f"Deleted {DEV_DIR}, {PROD_DIR} and each setup's (data/dev-*).")
    elif args.command == "prod":
        prod(args.from_backup, args.keep)
    elif args.command == "invite":
        settings = dev_settings(DEV_DIR, "http://127.0.0.1", os.environ)
        code = invite(settings, args.name)
        print(f'In the simulator, pick "Someone new" and send:  /start {code}')
    else:
        run(fakes=not args.no_fakes, setup=dev_setup(args.template, args.modules, args.config))


def prod(backup: str | None, keep: bool) -> None:
    """D4: copy (unless `keep`), clean, and run on the copy."""
    from tools.dev import prod_copy

    dest = PROD_DIR / "themi.db"
    if keep and not dest.exists():
        raise SystemExit(f"There's no copy in {PROD_DIR} yet; run without --keep.")
    if not keep:
        env = {**read_dotenv(Path(".env")), **os.environ}
        if backup:
            print(f"Restoring backup {backup} into {PROD_DIR}...", flush=True)
            prod_copy.from_backup(backup, dest)
            source = f"backup {backup}"
        else:
            host = env.get("THEMI_PI", PI)
            print(f"Copying the database from {host}...", flush=True)
            prod_copy.from_pi(host, dest)
            source = f"the Pi ({host})"
        prod_copy.clean(dest, source)
    run(PROD_DIR, copy=True)
