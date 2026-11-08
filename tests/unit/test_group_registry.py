"""CR8b: tool groups come from the modules that are loaded."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.fakes.modules import module_context
from tests.fixtures.family import SeededFamily
from themi.config import all_groups, any_group_of
from themi.core import groups
from themi.core.starter_tools import STARTER_TOOLS
from themi.core.tools import SETTINGS, ToolRegistry
from themi.standard.lists import ListsModule
from themi_home.recipes import RecipesModule


def more_tools_groups(registry: ToolRegistry) -> list[str]:
    spec = next(s for s in registry.specs() if s.name == "more_tools")
    return spec.input_schema["properties"]["groups"]["items"]["enum"]


def test_a_module_brings_its_groups_and_only_those_are_offered(family: SeededFamily) -> None:
    ctx = module_context(family.store)
    tools = ctx.services.tools
    for t in STARTER_TOOLS:
        tools.register(t)
    tools.add_group(SETTINGS)
    ctx.load(ListsModule())
    assert tools.group_names() == ["lists", "settings"]
    assert more_tools_groups(tools) == ["lists", "settings"]
    assert tools.group_of("create_list") == "lists"
    assert tools.group_of("find_recipe") == "core"  # recipes isn't loaded: no group for it
    assert tools.choose_groups(["make a packing list"]) == {"lists"}
    assert tools.choose_groups(["any recipes for soup?"]) == set()
    ctx.load(RecipesModule(None))
    assert tools.group_names() == ["recipes", "lists", "settings"]  # in the offered order


def test_two_modules_may_add_one_group_but_not_two_groups_with_one_name() -> None:
    registry = ToolRegistry()
    registry.add_group(groups.WALL)
    registry.add_group(groups.WALL)  # the wall's to-do lists and chores both have it
    with pytest.raises(ValueError, match="two different tool groups are called wall"):
        registry.add_group(replace(groups.WALL, description="something else"))


def test_the_catalog_has_every_group_once_in_order() -> None:
    names = [g.name for g in all_groups()]
    assert len(names) == len(set(names)) == 15
    assert [g.order for g in all_groups()] == sorted(g.order for g in all_groups())
    tools = [t for g in all_groups() for t in g.tools]
    assert len(tools) == len(set(tools))  # a tool is in one group
    assert any_group_of("find_recipe") == "recipes"
    assert any_group_of("create_task") == "core"
