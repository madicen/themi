"""SP3a: what a module says about itself on the Modules page."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.fixtures.family import SeededFamily
from themi.config import available_modules
from themi.modules import Module
from themi.modules.guides import guide
from themi.modules.settings import ModuleSettings, env_field, fields
from themi.standard.telegram import TelegramModule
from themi.storage.secrets import Secret
from themi.web.markdown import render
from tools import check_packs


class Every(ModuleSettings):
    name: str = env_field("X_NAME", "", ask="What to call it (blank: none)")
    key: Secret | None = env_field("X_KEY", secret=True, ask="The key")
    on: bool = env_field("X_ON", False, ask="Turn it on? (yes or no)")
    which: str = env_field("X_WHICH", "a", choices=("a", "b"), label="Which one")
    server_url: str = env_field("X_URL", "", placeholder="https://...")
    count: int = env_field("X_COUNT", 3, advanced=False)


def test_fields_say_what_kind_each_is() -> None:
    found = {f.name: f for f in fields(Every)}
    assert {n: f.kind for n, f in found.items()} == {
        "name": "text",
        "key": "secret",
        "on": "bool",
        "which": "choice",
        "server_url": "url",
        "count": "number",
    }
    assert found["name"].label == "What to call it"
    assert found["on"].label == "Turn it on"
    assert found["which"].label == "Which one" and found["which"].choices == ("a", "b")
    assert found["server_url"].label == "Server url" and found["server_url"].placeholder
    assert found["key"].secret and found["key"].env == "X_KEY"
    # a field the wizard never asked is folded away, unless it says otherwise
    assert not found["name"].advanced and found["which"].advanced
    assert found["server_url"].advanced and not found["count"].advanced
    assert found["count"].default == 3


def test_a_modules_guide_is_found_beside_its_code() -> None:
    text = guide(TelegramModule)
    assert text is not None and "@BotFather" in text

    class NoGuide(Module):
        name = "no_guide_here"

    assert guide(NoGuide) is None


def test_every_core_module_has_a_title_and_a_summary() -> None:
    for name, cls in available_modules().items():
        if cls.__module__.startswith("themi."):
            assert cls.title and cls.summary, name


def test_the_lint_fails_on_a_module_without_a_title(monkeypatch: pytest.MonkeyPatch) -> None:
    class Untitled(Module):
        name = "untitled"

    class Done(Module):
        name = "done"
        title = "Done"
        summary = "It's done."

    monkeypatch.setattr(
        "themi.config.available_modules", lambda: {"untitled": Untitled, "done": Done}
    )
    assert check_packs.manifest_problems(frozenset()) == [
        "module untitled needs a title and a summary"
    ]
    assert check_packs.manifest_problems(frozenset({"untitled", "done"})) == [
        "module done is done: take it out of PENDING in tools/check_packs.py"
    ]


def test_the_lint_wants_a_guide_when_there_are_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    class Asks(Module):
        name = "asks"
        title = "Asks"
        summary = "It asks."
        settings = Every

    monkeypatch.setattr("themi.config.available_modules", lambda: {"asks": Asks})
    assert check_packs.manifest_problems(frozenset()) == [
        "module asks needs a guide (setup/asks.md beside its code)"
    ]


def test_the_installed_modules_pass_the_lint() -> None:
    assert check_packs.manifest_problems() == []


# ----- the guides' Markdown --------------------------------------------------------------


def test_markdown_makes_headings_lists_and_links() -> None:
    html = render(
        "# Get a key\n\nGo to [Tavily](https://tavily.com) and **sign up**.\n\n"
        "1. Open `/newbot`\n2. Copy it,\n   then paste it\n\n- one\n- two\n\n"
        "See the [Family page](/family)."
    )
    assert "<h2>Get a key</h2>" in html
    assert '<a href="https://tavily.com" target="_blank" rel="noopener noreferrer">' in html
    assert "<strong>sign up</strong>" in html
    assert "<ol><li>Open <code>/newbot</code></li><li>Copy it, then paste it</li></ol>" in html
    assert "<ul><li>one</li><li>two</li></ul>" in html
    assert '<a href="/family">Family page</a>' in html


def test_markdown_allows_no_html_and_no_strange_links() -> None:
    html = render("<script>alert(1)</script> [x](javascript:alert(1)) [y](//evil.test) `<b>`")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "href" not in html
    assert "<code>&lt;b&gt;</code>" in html


# ----- SP3b: the packs -------------------------------------------------------------------


def test_every_module_is_done_and_the_allowlist_is_empty() -> None:
    assert frozenset() == check_packs.PENDING
    for name, cls in available_modules().items():
        assert cls.title and cls.summary, name


def test_each_pack_guide_is_found() -> None:
    known = available_modules()
    for name in ("google", "travel", "ourgroceries", "home_connect", "spotify"):
        assert guide(known[name]), name
    assert guide(known["cozyla_todos"]) and guide(known["cozyla_chores"])


def linked(cls: type[Module], services: object) -> bool | None:
    return Module.accounts_linked(object.__new__(cls), services)  # type: ignore[arg-type]


def test_each_account_check_reads_the_real_tables(family: SeededFamily) -> None:
    services = SimpleNamespace(store=family.store)
    needing = {n: c for n, c in available_modules().items() if c.needs_accounts is not None}
    assert set(needing) >= {"google", "spotify", "home_connect", "thinq", "roborock"}
    for name, cls in needing.items():
        assert linked(cls, services) is False, name  # nothing linked yet, and the query runs


def test_an_account_check_turns_true_once_linked(family: SeededFamily) -> None:
    services = SimpleNamespace(store=family.store)
    known = available_modules()
    family.db.execute(
        "INSERT INTO spotify_links (member_id, refresh_token, linked_at) VALUES (?, ?, ?)",
        (family.erin.id, b"x", "2026-11-08T00:00:00+00:00"),
    )
    family.db.execute(
        "INSERT INTO home_connect_account (id, refresh_token, linked_at) VALUES (1, ?, ?)",
        (b"x", "2026-11-08T00:00:00+00:00"),
    )
    assert linked(known["spotify"], services) is True
    assert linked(known["home_connect"], services) is True
    assert linked(known["thinq"], services) is False
    assert linked(known["tasks"], services) is None  # nothing to link
