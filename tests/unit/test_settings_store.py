"""SP2: the settings store: themi.toml written by Themi, secrets kept encrypted, a draft."""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path

import pytest

from tests.fixtures.db import migrated_file
from themi.config import (
    InstanceConfig,
    as_toml,
    config_path,
    load_config,
    parse_config,
    resolve_start,
    write_config,
    write_path,
)
from themi.core.connector_settings import SearchSettings
from themi.modules.settings import read_settings, value_sources
from themi.modules.store import Draft, DraftStore, ModuleSecrets
from themi.settings import Settings, SettingsError, ensure_secret_key
from themi.storage.secrets import Cipher, Secret, generate_key

KEY = generate_key()


def secrets_store(tmp_path: Path) -> ModuleSecrets:
    return ModuleSecrets(migrated_file(tmp_path / "themi.db"), Cipher(KEY))


# ----- precedence ----------------------------------------------------------------------


def test_the_environment_beats_a_stored_secret_which_beats_the_default() -> None:
    stored = {"tavily_api_key": Secret("stored-key")}
    from_env = read_settings(
        SearchSettings, {"TAVILY_API_KEY": "env-key"}, {}, "web_search", stored
    )
    assert from_env.tavily_api_key == Secret("env-key")
    from_store = read_settings(SearchSettings, {}, {}, "web_search", stored)
    assert from_store.tavily_api_key == Secret("stored-key")
    assert read_settings(SearchSettings, {}, {}, "web_search").tavily_api_key is None


def test_the_environment_beats_the_file_which_beats_the_default() -> None:
    section = {"backend": "firecrawl"}
    env = {"THEMI_SEARCH_BACKEND": "tavily"}
    assert read_settings(SearchSettings, env, section, "web_search").backend == "tavily"
    assert read_settings(SearchSettings, {}, section, "web_search").backend == "firecrawl"
    assert read_settings(SearchSettings, {}, {}, "web_search").backend == ""


def test_where_each_value_came_from() -> None:
    stored = {"tavily_api_key": Secret("k")}
    sources = value_sources(
        SearchSettings, {"FIRECRAWL_API_KEY": "f"}, {"backend": "tavily"}, stored
    )
    assert sources == {
        "tavily_api_key": "stored",
        "firecrawl_api_key": "environment",
        "backend": "file",
    }


def test_a_stored_secret_reaches_the_module_it_belongs_to(tmp_path: Path) -> None:
    store = secrets_store(tmp_path)
    store.set("travel", "tomtom_api_key", "tt-key", None)
    settings = Settings.from_mapping({"THEMI_SECRET_KEY": KEY})
    modules, _ = resolve_start(parse_config({}), settings, stored=store.all())
    travel = next(m for m in modules if m.name == "travel")
    assert travel.client.tomtom_key == Secret("tt-key")  # type: ignore[attr-defined]


# ----- the secrets table ---------------------------------------------------------------


def test_secrets_are_kept_encrypted_and_shown_only_by_their_ending(tmp_path: Path) -> None:
    store = secrets_store(tmp_path)
    store.set("web_search", "tavily_api_key", "tvly-abcd1234", None)
    raw = store._db.scalar("SELECT ciphertext FROM module_secrets")
    assert b"tvly-abcd1234" not in raw
    info = store.info("web_search")["tavily_api_key"]
    assert info.ending == "1234" and info.set_at
    store.set("web_search", "tavily_api_key", "tvly-new-9999", None)
    assert store.all()["web_search"]["tavily_api_key"] == Secret("tvly-new-9999")
    store.clear("web_search", "tavily_api_key")
    assert store.all() == {}


# ----- themi.toml -------------------------------------------------------------------


def test_secrets_never_go_in_the_toml() -> None:
    config = InstanceConfig(
        "family",
        ("travel",),
        ("safeway",),
        sections={"web_search": {"backend": "tavily"}},
        core={"public_url": "https://themi.example.ts.net"},
    )
    text = as_toml(config)
    assert "api_key" not in text
    back = parse_config(tomllib.loads(text))
    assert back.added == ("travel",) and back.removed == ("safeway",)
    assert back.sections == {"web_search": {"backend": "tavily"}}
    assert back.core == {"public_url": "https://themi.example.ts.net"}


def test_core_takes_only_what_it_knows() -> None:
    with pytest.raises(SettingsError, match=r"\[core\] has telegram_token"):
        parse_config({"core": {"telegram_token": "x"}})


def test_the_writer_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "themi.toml"
    write_config(InstanceConfig("family"), path)
    before = path.read_text()

    def crash(src: object, dst: object) -> None:
        raise OSError("power cut")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="power cut"):
        write_config(InstanceConfig("work"), path)
    assert path.read_text() == before  # the old file, whole
    assert not (tmp_path / ".themi.toml.tmp").exists()


def test_themi_writes_next_to_the_database_and_finds_it_there(tmp_path: Path) -> None:
    env = {"THEMI_DB_PATH": str(tmp_path / "data" / "themi.db")}
    path = write_path(InstanceConfig(), env)
    assert path == tmp_path / "data" / "themi.toml"
    assert config_path(env) is None
    write_config(InstanceConfig("work", ("travel",)), path)
    assert config_path(env) == path
    assert load_config(path).template == "work"
    read_from = tmp_path / "elsewhere.toml"
    assert write_path(InstanceConfig(path=read_from), env) == read_from


# ----- the draft -------------------------------------------------------------------------


def test_a_draft_keeps_its_changes_and_its_secrets_encrypted(tmp_path: Path) -> None:
    db = migrated_file(tmp_path / "themi.db")
    cipher = Cipher(KEY)
    drafts = DraftStore(db)
    assert drafts.get() is None
    draft = Draft(template="work", modules={"travel": True, "safeway": False})
    draft.sections["web_search"] = {"backend": "tavily"}
    draft.put_secret(cipher, "travel", "tomtom_api_key", "tt-secret")
    draft.put_secret(cipher, "web_search", "tavily_api_key", None)  # to clear
    draft.note(None, "turned on travel")
    drafts.save(draft, None)
    assert "tt-secret" not in db.scalar("SELECT body FROM config_drafts")
    back = drafts.get()
    assert back is not None
    assert back.template == "work" and back.modules == {"travel": True, "safeway": False}
    assert back.secret(cipher, "travel", "tomtom_api_key") == Secret("tt-secret")
    assert back.secrets["web_search"] == {"tavily_api_key": None}
    assert back.log[0]["what"] == "turned on travel"
    drafts.discard()
    assert drafts.get() is None
    drafts.save(Draft(), None)  # an empty draft is no draft
    assert drafts.get() is None


# ----- the secret key -------------------------------------------------------------------


def test_a_new_themi_makes_its_own_key_and_uses_it(tmp_path: Path) -> None:
    env = {"THEMI_DB_PATH": str(tmp_path / "themi.db")}
    made = ensure_secret_key(env)
    assert made is not None and made == tmp_path / "secret.key"
    assert stat.S_IMODE(made.stat().st_mode) == 0o600
    settings = Settings.from_mapping(env)
    assert settings.secret_key == Secret(made.read_text().strip())
    assert ensure_secret_key(env) is None  # made once


def test_a_key_is_never_made_for_an_existing_database(tmp_path: Path) -> None:
    migrated_file(tmp_path / "themi.db").close()
    env = {"THEMI_DB_PATH": str(tmp_path / "themi.db")}
    assert ensure_secret_key(env) is None
    with pytest.raises(SettingsError, match="THEMI_SECRET_KEY"):
        Settings.from_mapping(env)


def test_a_key_that_is_set_wins_and_nothing_is_made(tmp_path: Path) -> None:
    env = {"THEMI_DB_PATH": str(tmp_path / "themi.db"), "THEMI_SECRET_KEY": KEY}
    assert ensure_secret_key(env) is None
    assert not (tmp_path / "secret.key").exists()
