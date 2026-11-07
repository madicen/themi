"""CR11: `themi setup` writes themi.toml and .env, and tries what it can."""

from __future__ import annotations

import stat
import tomllib
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest

from themi.config import available_modules, load_config, resolve_modules
from themi.modules import Module, ModuleContext
from themi.settings import Settings, read_dotenv
from themi.setup_wizard import SetupCancelled, check_setup, run_setup


def answering(said: dict[str, str]):  # question words -> the answer typed
    def ask(question: str, default: str | None = None) -> str:
        return next((v for k, v in said.items() if k in question), "")

    return ask


def skip_checks(coro: Coroutine[Any, Any, str | None]) -> str | None:
    coro.close()  # no real services in the unit tests
    return None


def test_a_family_setup(tmp_path: Path) -> None:
    told: list[str] = []
    ask = answering(
        {
            "Which template": "family",
            "Leave any out": "safeway",
            "Google OAuth client id": "abc.apps.googleusercontent.com",
            "OurGroceries email": "us@x.example",
            "The OurGroceries list": "Groceries",
        }
    )
    secrets = answering(
        {
            "Telegram bot token": "123:abc",
            "Google OAuth client secret": "shh-google",
            "OurGroceries password": "shh-grocery",
        }
    )
    toml_path, env_path = run_setup(ask, secrets, told.append, tmp_path, run=skip_checks)
    config = tomllib.loads(toml_path.read_text())
    assert config["template"] == "family" and config["modules"] == ["-safeway"]
    assert config["module"]["google"] == {"client_id": "abc.apps.googleusercontent.com"}
    assert config["module"]["ourgroceries"]["username"] == "us@x.example"
    env = read_dotenv(env_path)
    assert env["TELEGRAM_BOT_TOKEN"] == "123:abc" and env["GOOGLE_CLIENT_SECRET"] == "shh-google"
    assert env["OURGROCERIES_PASSWORD"] == "shh-grocery" and env["THEMI_SECRET_KEY"]
    assert "shh" not in toml_path.read_text()  # secrets never go in themi.toml
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    names = [m.name for m in resolve_modules(load_config(toml_path), Settings.from_mapping(env))]
    assert "safeway" not in names and {"google", "gmail", "ourgroceries"} <= set(names)
    assert any("links their Google account on Accounts" in t for t in told)


def test_an_empty_setup_adds_what_a_module_needs(tmp_path: Path) -> None:
    told: list[str] = []
    ask = answering({"Which template": "empty", "Add any": "reminders, lists"})
    toml_path, _ = run_setup(ask, answering({}), told.append, tmp_path, run=skip_checks)
    config = tomllib.loads(toml_path.read_text())
    assert config["template"] == "empty"
    assert config["modules"] == ["+reminders", "+lists", "+tasks"]
    assert "tasks is added too: reminders needs it." in told


def test_an_unknown_name_is_asked_again(tmp_path: Path) -> None:
    told: list[str] = []
    answers = iter(["", "nope", "empty", "bogus", "", "", ""])
    run_setup(
        lambda q, d=None: next(answers, ""), answering({}), told.append, tmp_path, run=skip_checks
    )
    assert "There's no template called nope." in " ".join(told)
    assert "Not one of these: bogus." in told


class Broken(Module):
    name = "broken"

    async def check(self) -> str | None:
        return "it says no"

    def install(self, ctx: ModuleContext) -> None:
        pass


def test_a_failing_check_is_said_and_counted(tmp_path: Path) -> None:
    import asyncio

    known = {**available_modules(), "broken": Broken}
    told: list[str] = []
    ask = answering({"Which template": "empty", "Add any": "broken"})
    run_setup(ask, answering({}), told.append, tmp_path, known=known, run=asyncio.run)
    assert "broken: it says no" in told and "1 to look at." in told
    told.clear()
    assert check_setup(tmp_path, told.append, known=known) == 1  # --check, again
    assert "broken: it says no" in told


def test_a_file_there_already_is_kept_unless_they_say_so(tmp_path: Path) -> None:
    (tmp_path / "themi.toml").write_text('template = "family"\n')
    told: list[str] = []
    ask = answering({"Which template": "empty", "Replace it": "no"})
    with pytest.raises(SetupCancelled):
        run_setup(ask, answering({}), told.append, tmp_path, run=skip_checks)
    assert (tmp_path / "themi.toml").read_text() == 'template = "family"\n'
    assert not (tmp_path / ".env").exists()
    ask = answering({"Which template": "empty", "Replace it": "yes"})
    run_setup(ask, answering({}), told.append, tmp_path, run=skip_checks)
    assert 'template = "empty"' in (tmp_path / "themi.toml").read_text()


def test_the_wall_is_asked_about_once(tmp_path: Path) -> None:
    asked: list[str] = []

    def ask(question: str, default: str | None = None) -> str:
        asked.append(question)
        return {"Which template": "family", "Cozyla account email": "w@x.example"}.get(
            next((k for k in ("Which template", "Cozyla account email") if k in question), ""),
            "",
        )

    toml_path, _ = run_setup(ask, answering({}), lambda _: None, tmp_path, run=skip_checks)
    assert sum("Cozyla account email" in q for q in asked) == 1
    config = tomllib.loads(toml_path.read_text())
    assert config["module"]["cozyla_todos"] == config["module"]["cozyla_chores"]
