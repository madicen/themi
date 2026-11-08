"""CR21c: the Cozyla wall's modules. Each keeps something of Themi's in step on the wall:
`cozyla_todos` the to-do list and Themi's lists, `cozyla_chores` the chore chart and
routines (both the wall's own and Themi's)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from themi.core import groups
from themi.modules import Module, ModuleContext, ModuleSetup
from themi.modules.prompt import PromptFragment
from themi.standard.routines import Routines
from themi.standard.tasks import TaskBoard
from themi_cozyla.connector import CozylaClient
from themi_cozyla.cozyla_chores import CozylaChores
from themi_cozyla.cozyla_routines import CozylaRoutines
from themi_cozyla.cozyla_todos import CozylaTodos
from themi_cozyla.routines_wall import RoutinesWall
from themi_cozyla.settings import CozylaSettings


def _wall(setup: ModuleSetup) -> CozylaClient | None:
    """One Cozyla client for both wall modules, as before (CR5a)."""
    config = setup.read(CozylaSettings).config()
    return setup.shared("cozyla", lambda: CozylaClient(config)) if config else None


def _wall_in_family_time(ctx: ModuleContext, cozyla: CozylaClient) -> None:
    family = ctx.services.store.get_family()
    cozyla.timezone = family.timezone if family else cozyla.timezone


class CozylaTodosModule(Module):
    """The Cozyla wall's to-do list, kept in step with Themi's tasks."""

    name = "cozyla_todos"
    title = "Cozyla to-do lists"
    summary = "Keeps the Cozyla wall's to-do lists in step with Themi's tasks."
    cost = "Unofficial: may stop working"
    kind = "connector"
    tool_groups = (
        groups.LISTS,
        groups.WALL,
    )
    settings = CozylaSettings
    requires = ("tasks",)
    migrations = Path(__file__).parent / "cozyla_todos_schema"  # CR21b: the wall's lists

    def __init__(self, client: CozylaClient) -> None:
        self.client = client

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        wall = _wall(setup)
        return cls(wall) if wall and wall.config.todo_list else None

    async def check(self) -> str | None:
        from themi_cozyla.connector.check import check

        try:
            await check(self.client)
        except Exception as exc:  # whatever went wrong, said once, for Test
            return f"The Cozyla wall didn't answer: {exc}"
        return None

    def install(self, ctx: ModuleContext) -> None:
        _wall_in_family_time(ctx, self.client)
        wall = ctx.provide(CozylaTodos(ctx.services, ctx.get(TaskBoard), self.client))
        wall.install()
        ctx.periodic("cozyla.sync", timedelta(minutes=1), wall.sync)


# CR8a: the system prompt's rules about this module's feature.
CHORE_PROMPT_RULES = (
    PromptFragment(
        "cozyla_chores.how-many-chores-someone",
        "act",
        110,
        """\
- How many chores someone sees on the wall's chore chart at once is a setting too
  (set_chore_chart_limit), not a rule; "a different one" or "another one" is
  change_chore_chart.""",
    ),
    PromptFragment(
        "cozyla_chores.an-item-for-someone",
        "act",
        130,
        """\
- An item for someone's morning, afternoon or evening routine on the wall is
  add_to_wall_routine: not a calendar event, a chore or a list.""",
    ),
)


class CozylaChoresModule(Module):
    """The Cozyla wall's chore chart and routines, and Themi's routines shown there."""

    name = "cozyla_chores"
    title = "Cozyla chores and routines"
    summary = "Keeps the Cozyla wall's chore chart and routines in step with Themi's."
    cost = "Unofficial: may stop working"
    kind = "connector"
    tool_groups = (groups.WALL,)
    settings = CozylaSettings
    requires = ("tasks", "routines", "chore_chart")
    migrations = (
        Path(__file__).parent / "cozyla_chores_schema"
    )  # CR21b: what the wall saw  # CR21a: it shows the chart on the wall

    def __init__(self, client: CozylaClient) -> None:
        self.client = client

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        wall = _wall(setup)
        return cls(wall) if wall and wall.config.chores else None

    async def check(self) -> str | None:
        from themi_cozyla.connector.check import check

        try:
            await check(self.client)
        except Exception as exc:  # whatever went wrong, said once, for Test
            return f"The Cozyla wall didn't answer: {exc}"
        return None

    def install(self, ctx: ModuleContext) -> None:
        ctx.prompt(*CHORE_PROMPT_RULES)
        _wall_in_family_time(ctx, self.client)
        s, tasks = ctx.services, ctx.get(TaskBoard)
        chart = ctx.provide(CozylaChores(s, tasks, self.client))
        chart.install()
        ctx.periodic("cozyla.chores", timedelta(minutes=5), chart.sync)
        wall_routines = ctx.provide(CozylaRoutines(s, tasks, self.client))
        wall_routines.install()
        ctx.periodic("cozyla.routines", timedelta(minutes=15), wall_routines.sync)
        mirror = ctx.provide(RoutinesWall(s, ctx.get(Routines), wall_routines, self.client))
        mirror.install()
        ctx.periodic("routines.wall", timedelta(minutes=5), mirror.sync)
