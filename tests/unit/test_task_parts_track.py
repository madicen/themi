"""F26c on the module system: the parts' table is the task_parts module's own track, and
the task board works without it (the work template has tasks but no task parts)."""

from __future__ import annotations

from tests.fakes.modules import module_context
from tests.fixtures.family import SeededFamily
from themi.standard.task_parts import TaskPartsModule
from themi.standard.tasks import TaskBoard, TasksModule
from themi.storage.migrations import current_version


def tables(family: SeededFamily) -> set[str]:
    rows = family.db.query("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {r["name"] for r in rows}


async def test_tasks_without_task_parts_has_no_parts_table_and_still_works(
    family: SeededFamily,
) -> None:
    ctx = module_context(family.store)
    ctx.load(TasksModule())
    assert "task_parts" not in tables(family)  # not in the core schema
    board = ctx.get(TaskBoard)
    assert board.set_aside == []
    erin = family.store.list_members()[0]
    task = await board.create(erin, "Call the vet", "call", 1, assignee=erin)
    assert [t.id for t in board.open_for(erin)] == [task.id]
    assert board.matcher.task_load(erin) > 0


def test_task_parts_brings_its_own_track(family: SeededFamily) -> None:
    ctx = module_context(family.store)
    ctx.load(TasksModule(), TaskPartsModule())
    assert "task_parts" in tables(family)
    assert current_version(family.db, "task_parts") == 1
    assert ctx.get(TaskBoard).set_aside == ["SELECT parent_id FROM task_parts"]
