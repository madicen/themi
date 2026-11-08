"""SP1: a module's problem leaves that module (and what needs it) off, and Themi starts."""

from __future__ import annotations

import tomllib

import pytest

from tests.fixtures.family import SeededFamily
from themi.accounts import Member
from themi.app import build_app
from themi.config import available_modules, load_template, parse_config, resolve_start
from themi.modules import Module, ModuleContext, ModuleSetup, StartReport
from themi.modules.settings import SettingsProblem
from themi.settings import Settings, SettingsError
from themi.storage.secrets import generate_key

KEY = generate_key()
GOOGLE = {"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret"}


def settings(**env: str) -> Settings:
    return Settings.from_mapping({"THEMI_SECRET_KEY": KEY, **env})


def config(text: str = ""):
    return parse_config(tomllib.loads(text))


class BrokenGoogle(Module):
    name = "google"
    kind = "connector"

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        raise SettingsProblem(["GOOGLE_CLIENT_ID doesn't look like a Google client id"])


def test_a_module_whose_settings_fail_is_left_off_with_what_needs_it() -> None:
    known = {**available_modules(), "google": BrokenGoogle}
    modules, report = resolve_start(config(), settings(**GOOGLE), known)
    names = [m.name for m in modules]
    assert "google" not in names and "gmail" not in names and "email_triage" not in names
    assert "tasks" in names and "reminders" in names  # the rest start
    assert report.state("google") == "failed"
    assert "doesn't look like a Google client id" in report.modules["google"].reason
    assert report.state("gmail") == "off"
    assert report.modules["gmail"].reason == "it needs google, which isn't on"
    assert any(w.startswith("google couldn't start:") for w in report.warnings())


def test_a_build_that_raises_is_left_off_too() -> None:
    class Exploding(BrokenGoogle):
        @classmethod
        def build(cls, setup: ModuleSetup) -> Module | None:
            raise RuntimeError("the client library is missing")

    known = {**available_modules(), "google": Exploding}
    _, report = resolve_start(config(), settings(**GOOGLE), known)
    assert report.state("google") == "failed"
    assert "the client library is missing" in report.modules["google"].reason


def test_a_problem_with_the_file_itself_still_stops() -> None:
    with pytest.raises(SettingsError, match="there's no module called bogus"):
        resolve_start(config('modules = ["+bogus"]'), settings())
    with pytest.raises(SettingsError, match="no template called school"):
        resolve_start(config('template = "school"'), settings())


def test_no_ai_provider_starts_with_a_warning() -> None:
    known = available_modules()
    providers = [n for n in load_template("family").modules if known[n].kind == "ai"]
    assert providers
    text = "modules = [" + ", ".join(f'"-{n}"' for n in providers) + "]"
    modules, report = resolve_start(config(text), settings())
    assert modules  # it starts
    assert not report.has_ai()
    warning = report.warnings()[0]
    assert warning.startswith("Themi has no AI provider yet, so it can't answer.")
    assert "gemini" in warning


def test_telegram_without_a_token_is_not_set_up_and_said() -> None:
    unavailable = {"telegram": "it needs a bot token (TELEGRAM_BOT_TOKEN, from @BotFather)"}
    modules, report = resolve_start(config(), settings(), unavailable=unavailable)
    assert "telegram" not in [m.name for m in modules]
    assert report.state("telegram") == "not_set_up"
    assert "telegram isn't on: it needs a bot token" in "\n".join(report.warnings())


def test_removed_and_unconfigured_modules_say_why() -> None:
    _, report = resolve_start(config('modules = ["-safeway"]'), settings())
    assert report.modules["safeway"].reason == "removed in themi.toml"
    assert report.state("gmail") in ("not_set_up", "off")
    lines = "\n".join(report.lines())
    assert "safeway (off): removed in themi.toml" in lines


# ----- installing --------------------------------------------------------------------


async def nothing(member: Member, text: str) -> None:
    return None


class Fine(Module):
    name = "fine"

    def install(self, ctx: ModuleContext) -> None:
        ctx.command("fine", nothing, "A command that works")


class Breaks(Module):
    name = "breaks_on_install"

    def install(self, ctx: ModuleContext) -> None:
        ctx.command("half", nothing, "Added before it raised")
        ctx.capability("half_there")
        ctx.services.prompt_fragments.append("added straight on the services")  # type: ignore[arg-type]
        raise RuntimeError("its service answered 500")


class NeedsBroken(Module):
    name = "needs_broken"
    requires = ("breaks_on_install",)

    def install(self, ctx: ModuleContext) -> None:
        ctx.command("needs", nothing, "Never added")


def test_an_install_that_raises_is_taken_back_and_left_out(family: SeededFamily) -> None:
    report = StartReport()
    app = build_app(
        family.db,
        family.store.cipher,
        None,
        modules=[Fine(), Breaks(), NeedsBroken()],
        report=report,
    )
    assert [m.name for m in app.modules] == ["fine"]
    assert "fine" in app.services.commands
    assert "half" not in app.services.commands and "needs" not in app.services.commands
    assert "half_there" not in app.services.capabilities
    assert "added straight on the services" not in app.services.prompt_fragments
    assert app.services.start_report is report
    assert report.state("breaks_on_install") == "failed"
    assert "its service answered 500" in report.modules["breaks_on_install"].reason
    assert report.state("needs_broken") == "off"
    assert "breaks_on_install, which couldn't start" in report.modules["needs_broken"].reason


def test_without_a_report_an_install_that_raises_still_stops(family: SeededFamily) -> None:
    with pytest.raises(RuntimeError, match="its service answered 500"):
        build_app(family.db, family.store.cipher, None, modules=[Fine(), Breaks()])
