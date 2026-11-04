"""D4, Michael's idea #136: `make dev-prod`, dev on a copy of the Pi's data. The copy is
cleaned so dev never reaches the family: no tokens, keys or sign-ins, and Telegram ids that
are the simulator's people."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from tests.fixtures.family import ERIN_TELEGRAM_ID, HUSBAND_TELEGRAM_ID, seed_family
from themi.accounts import SYSTEM, AccountStore
from themi.ai.settings import AISettingsStore
from themi.storage import open_database
from themi.storage.secrets import Cipher, Secret, generate_key
from tools.dev import prod_copy, runner

NOW = "2026-11-03T20:00:00+00:00"


def prod_database(path: Path) -> None:
    """A small "prod" database: real-looking Telegram ids, a Gmail link with mail, AI keys,
    a Keep link, a website session, a paired Safeway helper and a message waiting."""
    cipher = Cipher(generate_key())
    store = AccountStore(open_database(path), cipher)
    family = seed_family(store)
    db = store.db
    db.execute("UPDATE members SET telegram_user_id = telegram_user_id + 7000000")
    account = store.add_linked_account(
        SYSTEM, family.erin.id, "gmail", "erin@gmail.com", Secret("1//real-refresh")
    )
    db.execute(
        "INSERT INTO emails (account_id, gmail_id, thread_id, from_address, subject, "
        "received_at, created_at) VALUES (?, 'g1', 't1', 'bank@example.com', 'Statement', ?, ?)",
        (account.id, NOW, NOW),
    )
    ai = AISettingsStore(db, cipher)
    for member in (family.erin, family.husband):
        ai.ensure_defaults(member.id)
        for backend in ai.backends(member.id):
            ai.update_backend(SYSTEM, backend.id, api_key=Secret("AIza-the-familys-own-key"))
    db.execute(
        "INSERT INTO keep_accounts (member_id, email, master_token, device_id, list_name, "
        "linked_at) VALUES (?, 'erin@gmail.com', ?, 'dev1', 'Groceries', ?)",
        (family.erin.id, cipher.encrypt("aas_et/master"), NOW),
    )
    db.execute(
        "INSERT INTO app_secrets (name, ciphertext, updated_at) VALUES ('cozyla', ?, ?)",
        (cipher.encrypt("password"), NOW),
    )
    db.execute(
        "INSERT INTO safeway_helpers (member_id, token_hash, created_at) VALUES (?, 'h', ?)",
        (family.erin.id, NOW),
    )
    db.execute(
        "INSERT INTO outbox (member_id, text, priority, status, send_after, created_at) "
        "VALUES (?, 'Due today: Refill auto feeders', 'normal', 'queued', ?, ?)",
        (family.husband.id, NOW, NOW),
    )
    store.db.close()


def rows(path: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(path) as db:
        return db.execute(sql).fetchall()


def test_the_copy_keeps_the_familys_data_and_nothing_that_reaches_them(tmp_path: Path) -> None:
    path = tmp_path / "themi.db"
    prod_database(path)
    prod_copy.clean(path)

    assert rows(path, "SELECT name, telegram_user_id FROM members ORDER BY id") == [
        ("Erin", ERIN_TELEGRAM_ID),
        ("Husband", HUSBAND_TELEGRAM_ID),
    ]
    assert rows(path, "SELECT refresh_token, enabled, watched FROM linked_accounts") == [
        (b"", 0, 0)
    ]
    assert rows(path, "SELECT subject FROM emails") == [("Statement",)]  # mail is kept
    assert rows(path, "SELECT COUNT(*) FROM ai_backends WHERE api_key IS NOT NULL") == [(0,)]
    for table in ("keep_accounts", "app_secrets", "safeway_helpers", "web_sessions"):
        assert rows(path, f"SELECT COUNT(*) FROM {table}") == [(0,)], table
    assert rows(path, "SELECT text, status FROM outbox") == [
        ("Due today: Refill auto feeders", "queued")
    ]  # for the simulator
    assert rows(path, "SELECT value FROM meta WHERE key = 'dev_prod_copy'")


def test_the_copy_opens_on_dev_with_its_own_key(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    prod_database(dev / "themi.db")
    prod_copy.clean(dev / "themi.db")
    settings = runner.dev_settings(dev, "http://127.0.0.1:9", {})
    assert prod_copy.put_dev_key(settings, "AIza-dev-key") == 2
    store = AccountStore(open_database(settings.db_path), settings.cipher())
    ai = AISettingsStore(store.db, settings.cipher())
    assert all(
        b.has_key for m in store.list_members() for b in ai.backends(m.id) if b.kind == "gemini"
    )
    assert (runner.login_link(settings) or "").startswith("http://127.0.0.1:8081/login/")
    store.db.close()


def test_the_pis_database_comes_over_ssh(tmp_path: Path) -> None:
    source = tmp_path / "pi.db"
    prod_database(source)
    calls: list[list[str]] = []

    def fake_ssh(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        with sqlite3.connect(source) as db:
            data = db.serialize()
        return subprocess.CompletedProcess(command, 0, data, b"")

    dest = tmp_path / "copy" / "themi.db"
    prod_copy.from_pi("themi@themi", dest, run=fake_ssh)
    (command,) = calls
    assert command[:3] == ["ssh", "-o", "BatchMode=yes"] and "themi@themi" in command
    assert "mode=ro" in command[-1] and "serialize" in command[-1]
    assert rows(dest, "SELECT name FROM members ORDER BY id") == [("Erin",), ("Husband",)]


def test_a_failed_copy_says_why_and_leaves_nothing(tmp_path: Path) -> None:
    def failing(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 255, b"", b"ssh: connect to host themi")

    dest = tmp_path / "copy" / "themi.db"
    with pytest.raises(SystemExit, match="connect to host"):
        prod_copy.from_pi("themi@themi", dest, run=failing)
    with pytest.raises(SystemExit, match="isn't a database"):
        prod_copy.from_pi(
            "themi@themi",
            dest,
            run=lambda c, **k: subprocess.CompletedProcess(c, 0, b"Error: no such service", b""),
        )
    assert not dest.exists()


def test_the_banner_says_its_the_familys_data(tmp_path: Path) -> None:
    banner = runner._banner(
        "http://127.0.0.1:8090", "link", runner.SeedResult(False, True), tmp_path, "the Pi"
    )
    assert "A private copy of the family's data (the Pi)" in banner
    assert "nothing goes to Telegram" in banner


def test_keep_needs_a_copy_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "PROD_DIR", tmp_path / "dev-prod")
    with pytest.raises(SystemExit, match="no copy"):
        runner.prod(None, keep=True)
