"""F33b (reply 237): more_tools offers only the groups this turn doesn't have. 29 of 41
calls that week asked for groups already sent, each a wasted model round."""

from typing import Any

from tests.fixtures.family import SeededFamily
from themi.ai.types import ToolCall, ToolSpec
from themi.core.routines import remove_routine_item, show_routines
from themi.core.starter_tools import STARTER_TOOLS
from themi.core.tools import GROUPS, ToolContext, ToolRegistry


def offered(specs: list[ToolSpec]) -> list[str] | None:
    spec = next((s for s in specs if s.name == "more_tools"), None)
    if spec is None:
        return None
    return spec.input_schema["properties"]["groups"]["items"]["enum"]


def test_only_groups_not_sent_are_offered() -> None:
    tools = ToolRegistry(list(STARTER_TOOLS))
    have = {"core", "calendar", "schedules", "wall"}
    enum = offered(tools.specs_for(have))
    assert enum == [g for g in GROUPS if g not in have]
    more = next(s for s in tools.specs_for(have) if s.name == "more_tools")
    assert "'wall'" not in more.description and "'calendar'" not in more.description
    assert "'pantry'" in more.description


def test_with_every_group_more_tools_isnt_sent() -> None:
    tools = ToolRegistry(list(STARTER_TOOLS))
    assert offered(tools.specs_for(set(GROUPS))) is None


def test_every_group_is_offered_without_a_turn() -> None:
    tools = ToolRegistry(list(STARTER_TOOLS))
    assert offered(tools.specs()) == list(GROUPS)


class FakeServices:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools


async def test_a_call_for_a_group_thats_here_names_its_tools(family: SeededFamily) -> None:
    tools = ToolRegistry([*STARTER_TOOLS, show_routines, remove_routine_item])
    ctx = ToolContext(family.erin, FakeServices(tools), groups={"wall"})  # type: ignore[arg-type]
    args: dict[str, Any] = {"groups": ["wall"]}
    result = await tools.run(ToolCall("c1", "more_tools", args), ctx)
    assert result.content.startswith("The wall tools are here already: ")
    assert "show_routines" in result.content and "remove_routine_item" in result.content
    assert result.content.endswith("Use one of them now.")
