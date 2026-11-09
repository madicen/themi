"""CR16: the simulator with any module setup, on the same fakes."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.dev import Boot
from themi.config import load_template, parse_config, resolve_modules
from themi.modules import Module, ModuleContext
from themi.settings import Settings
from themi.storage.secrets import generate_key
from tools.dev.runner import DEV_DIR, dev_setup


def test_the_family_with_no_changes_is_as_before() -> None:
    setup = dev_setup()
    assert setup.config is None and setup.dev_dir == DEV_DIR and setup.name == "family"


def test_each_setup_has_its_own_data() -> None:
    work = dev_setup(template="work")
    assert work.config is not None and work.config.template == "work"
    assert work.dev_dir == Path("data/dev-work")
    changed = dev_setup(modules="-safeway, +travel")
    assert changed.config is not None
    assert (changed.config.removed, changed.config.added) == (("safeway",), ("travel",))
    assert changed.dev_dir != DEV_DIR and changed.dev_dir != work.dev_dir


def test_a_themi_toml_names_the_setup(tmp_path: Path) -> None:
    path = tmp_path / "tutor.toml"
    path.write_text('template = "work"\nmodules = ["-focus"]\n')
    setup = dev_setup(config=str(path))
    assert setup.name == "tutor" and setup.dev_dir == Path("data/dev-tutor")
    assert setup.config is not None and setup.config.removed == ("focus",)


def test_what_the_modules_page_wrote_wins_after_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SP6: a restart from the Modules page in `make dev` comes back with its changes."""
    monkeypatch.chdir(tmp_path)
    DEV_DIR.mkdir(parents=True)
    (DEV_DIR / "themi.toml").write_text('template = "family"\nmodules = ["-safeway"]\n')
    setup = dev_setup()
    assert setup.config is not None and setup.config.removed == ("safeway",)
    assert setup.dev_dir == DEV_DIR and "Modules page" in setup.name
    work = Path("data/dev-work")
    work.mkdir()
    (work / "themi.toml").write_text('template = "work"\nmodules = ["+travel"]\n')
    assert dev_setup(template="work").config.added == ("travel",)  # type: ignore[union-attr]


def test_an_unknown_template_says_so_before_anything_starts() -> None:
    from themi.settings import SettingsError

    with pytest.raises(SettingsError, match="no template called nope"):
        dev_setup(template="nope")


def test_modules_given_already_are_used_and_one_not_given_is_left_out() -> None:
    class Plain(Module):
        def install(self, ctx: ModuleContext) -> None:
            pass

    given: dict[str, Module] = {}
    for name in ("gemini", "tasks", "reminders", "memory"):  # CR19: one AI provider at least
        module = Plain()
        module.name = name  # type: ignore[misc]  # an instance's own name, for the test
        given[name] = module
    config = parse_config({"template": "work"})
    settings = Settings.from_mapping({"THEMI_SECRET_KEY": generate_key()})
    names = [m.name for m in resolve_modules(config, settings, given=given)]
    assert names == [n for n in load_template("work").modules if n in given]


async def test_a_work_setup_runs_on_the_fakes(boot: Boot) -> None:
    run = await boot(parse_config({"template": "work"}))
    names = [m.name for m in run.runtime.app.modules]
    # every one, Google on its fakes; SL5: Slack's chat is the simulator's Telegram here
    wanted = [n for n in load_template("work").modules if n != "slack"]
    assert [n for n in names if n != "telegram"] == wanted and "telegram" in names
    assert "groceries" not in names and "cozyla_todos" not in names
    assert run.runtime.app.services.system_text().startswith("You are Themi, a work assistant")
    assert run.runtime.app.store.get_workspace().template == "work"  # type: ignore[union-attr]
    assert any("Google" in line for line in run.linked)  # the fakes linked what it has


async def test_the_family_setup_runs_as_before(boot: Boot) -> None:
    run = await boot()
    assert "cozyla_todos" in [m.name for m in run.runtime.app.modules]
    assert run.runtime.app.services.system_text().startswith("You are Themi, a household")
