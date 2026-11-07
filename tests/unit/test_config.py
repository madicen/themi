"""CR5a: themi.toml, the family template, and modules built from settings."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from themi.app import family_modules
from themi.config import (
    available_modules,
    config_path,
    load_config,
    load_template,
    parse_config,
    resolve_modules,
)
from themi.settings import Settings, SettingsError
from themi.storage.secrets import generate_key

KEY = generate_key()
GOOGLE = {"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret"}
COZYLA = {"COZYLA_EMAIL": "a@b.c", "COZYLA_PASSWORD": "pw"}


def settings(**env: str) -> Settings:
    return Settings.from_mapping({"THEMI_SECRET_KEY": KEY, **env})


def before_cr5a(s: Settings) -> list[str]:
    """The module list `build_runtime` gave before CR5a: its options, as it built them."""
    from themi.connectors.catgenie import CatGenieConfig
    from themi.connectors.cozyla import CozylaClient
    from themi.connectors.gkeep import GKeepAccount
    from themi.connectors.homeconnect import HomeConnectClient
    from themi.connectors.ourgroceries import OurGroceriesClient
    from themi.connectors.roborock import library as roborock_library
    from themi.connectors.search import choose as choose_search
    from themi.connectors.spotify import SpotifyClient
    from themi.connectors.thinq import mqtt as thinq_mqtt
    from themi.connectors.travel import TravelClient
    from themi.connectors.tuya import TuyaConfig

    options: dict[str, Any] = {
        "google": s.google(),
        "grocery_list": OurGroceriesClient(g) if (g := s.ourgroceries()) else None,
        "cozyla": CozylaClient(w) if (w := s.cozyla()) else None,
        "travel": TravelClient(s.tomtom_api_key),
        "search": choose_search(s.search_backend, s.tavily_api_key, s.firecrawl_api_key),
        "home_connect": HomeConnectClient(h) if (h := s.home_connect()) else None,
        "spotify": SpotifyClient(sp) if (sp := s.spotify()) else None,
        "thinq": dataclasses.replace(s.thinq(), mqtt=thinq_mqtt.available()),
        "roborock": roborock_library.available(),
        "tuya": TuyaConfig(),
        "catgenie": CatGenieConfig(),
        "keep": GKeepAccount,
    }
    return [m.name for m in family_modules(**options)]


def names(config_text: str = "", **env: str) -> list[str]:
    import tomllib

    config = parse_config(tomllib.loads(config_text))
    return [m.name for m in resolve_modules(config, settings(**env))]


@pytest.mark.parametrize(
    "env",
    [
        {},
        GOOGLE,
        {**GOOGLE, **COZYLA, "COZYLA_TODO_LIST": "Family", "COZYLA_CHORES": "1"},
        {**COZYLA, "COZYLA_CHORES": "yes"},
        {"OURGROCERIES_USERNAME": "u", "OURGROCERIES_PASSWORD": "p", "SPOTIFY_CLIENT_ID": "s"},
        {"HOME_CONNECT_CLIENT_ID": "h", "HOME_CONNECT_CLIENT_SECRET": "s", "TAVILY_API_KEY": "t"},
    ],
    ids=["nothing", "google", "google-and-wall", "wall-chores", "groceries-music", "dishwasher"],
)
def test_no_file_gives_the_module_list_build_runtime_gave(env: dict[str, str]) -> None:
    s = settings(**env)
    assert [m.name for m in resolve_modules(load_config(None), s)] == before_cr5a(s)


def test_the_family_template_is_family_modules_in_order() -> None:
    every = SimpleNamespace(tasks_url="x", config=SimpleNamespace(todo_list="F", chores=True))
    full = family_modules(
        **{
            k: every
            for k in (
                "google",
                "grocery_list",
                "cozyla",
                "travel",
                "home_connect",
                "spotify",
                "thinq",
                "roborock",
                "tuya",
                "catgenie",
                "keep",
            )
        }  # type: ignore[arg-type]
    )
    assert load_template("family").modules == tuple(m.name for m in full)


def test_every_installed_module_is_found_by_its_name() -> None:
    known = available_modules()
    assert set(load_template("family").modules) <= set(known)
    assert all(cls.name == name for name, cls in known.items())


def test_a_module_can_be_left_out() -> None:
    assert "safeway" not in names('modules = ["-safeway"]')
    assert "safeway" in names()


def test_leaving_out_what_another_needs_says_which() -> None:
    with pytest.raises(SettingsError, match=r"reminders needs tasks, which themi\.toml removes"):
        names('modules = ["-tasks"]')


def test_an_unknown_module_stops_startup() -> None:
    with pytest.raises(SettingsError, match="there's no module called bogus") as caught:
        names('modules = ["+bogus"]')
    assert str(caught.value).count("bogus") == 1


def test_a_module_named_but_not_set_up_stops_startup() -> None:
    with pytest.raises(SettingsError, match=r"spotify is added in themi\.toml, but its settings"):
        names('modules = ["+spotify"]')
    assert "spotify" in names('modules = ["+spotify"]', SPOTIFY_CLIENT_ID="s")


def test_a_template_connector_not_set_up_is_left_out_with_what_needs_it() -> None:
    found = names()
    assert not {"google", "gmail", "calendar", "email_audit", "google_tasks"} & set(found)
    assert {"google", "gmail", "calendar", "email_audit", "google_tasks"} <= set(names(**GOOGLE))


def test_an_unknown_template_stops_startup() -> None:
    with pytest.raises(SettingsError, match="no template called school"):
        names('template = "school"')


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('modules = ["safeway"]', 'modules lists "\\+name" or "-name"'),
        ('colour = "blue"', "colour isn't something themi.toml sets"),
        ("[module]\ngmail = 3", r"\[module.gmail\] is a section of settings"),
    ],
)
def test_a_malformed_file_says_what_is_wrong(text: str, problem: str) -> None:
    import tomllib

    with pytest.raises(SettingsError, match=problem):
        parse_config(tomllib.loads(text))


def test_sections_and_workspace_are_kept(tmp_path: Path) -> None:
    path = tmp_path / "themi.toml"
    path.write_text('[workspace]\nname = "Work"\n\n[module.gmail]\npoll_minutes = 2\n')
    config = load_config(path)
    assert config.workspace == {"name": "Work"}
    assert config.sections == {"gmail": {"poll_minutes": 2}}
    assert config.path == path


def test_the_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert config_path({}) is None
    (tmp_path / "themi.toml").write_text("")
    assert config_path({}) == Path("themi.toml")
    named = tmp_path / "other.toml"
    named.write_text("")
    assert config_path({"THEMI_CONFIG": str(named)}) == named
    with pytest.raises(SettingsError, match="THEMI_CONFIG names"):
        config_path({"THEMI_CONFIG": str(tmp_path / "missing.toml")})


def test_config_show(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from themi.cli import config_report

    path = tmp_path / "themi.toml"
    path.write_text('modules = ["-safeway"]\n[module.gmail]\npoll_minutes = 2\n')
    report = config_report(settings(), {"THEMI_CONFIG": str(path)})
    assert f"Config: {path}" in report and "Template: family" in report
    assert "  tasks\n" in report and "  safeway" in report.split("Left out")[1]
    assert "[module.gmail]\n  poll_minutes = 2" in report
