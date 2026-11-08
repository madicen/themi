"""CR9: a workspace made from a template, its roles, and two workspaces in one process."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily, seed_family
from tests.scenarios.test_module_lists import build
from themi.accounts import AccountStore
from themi.ai.types import ToolCall
from themi.app import family_modules
from themi.config import RoleSpec, load_template
from themi.core.tools import ToolContext
from themi.standard.tasks import TaskBoard
from themi.storage import open_database
from themi.storage.secrets import Cipher, generate_key


def test_the_workspace_knows_its_template(family: SeededFamily) -> None:
    workspace = family.store.get_workspace()
    assert workspace is not None and workspace.template == "family"
    assert family.store.get_family() == workspace  # the old name still answers


async def test_a_role_sees_and_runs_only_its_modules_tools(
    family: SeededFamily, fake_telegram: FakeTelegram
) -> None:
    template = load_template("family")
    limited = replace(
        template, roles={**template.roles, "member": RoleSpec("member", modules=("lists",))}
    )
    app = build(family, fake_telegram, family_modules(), template=limited)
    services, tools = app.services, app.services.tools
    every = set(tools.group_names())
    erin, husband = family.erin, family.husband
    hers = {s.name for s in tools.specs_for(every, "all", services.allowed_modules(erin))}
    his = {s.name for s in tools.specs_for(every, "all", services.allowed_modules(husband))}
    assert "find_recipe" in hers and "find_recipe" not in his
    assert "create_list" in his  # the lists module's
    assert "create_task" not in his  # the tasks module's
    assert "log_energy_level" in his  # the core's always go
    assert {tools.module_of(n) for n in his} <= {"core", "lists"}
    result = await tools.run(
        ToolCall("c1", "find_recipe", {"query": "soup"}), ToolContext(husband, services)
    )
    assert result.is_error and "Husband can't use find_recipe here" in result.content


def test_two_workspaces_in_one_process_keep_to_their_own(
    tmp_path: Path, fake_telegram: FakeTelegram
) -> None:
    one = seed_family(AccountStore(open_database(tmp_path / "one.db"), Cipher(generate_key())))
    two = seed_family(AccountStore(open_database(tmp_path / "two.db"), Cipher(generate_key())))
    first = build(one, fake_telegram, family_modules())
    second = build(two, fake_telegram, family_modules())
    import asyncio

    asyncio.run(
        first.services.get(TaskBoard).create(
            one.erin, "Only in one", "errand", 1, date(2026, 10, 21)
        )
    )
    titles = {t.title for t in first.services.get(TaskBoard).open_for(one.erin)}
    assert "Only in one" in titles
    assert not any(
        t.title == "Only in one" for t in second.services.get(TaskBoard).open_for(two.erin)
    )
    assert first.services.get(TaskBoard) is not second.services.get(TaskBoard)
