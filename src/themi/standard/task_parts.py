"""A task's steps split into tasks of their own (F26c, Michael's idea #142).

"Split Merlin's cat box up", "I'll do the first part", "give her the last step":
`split_task` turns every step of a one-off task into a task of its own, a part. The steps
they name go to whoever they say ('me', the partner, either of you: whoever has room);
the rest stay with the task's assignee. A due date they give is the part's; otherwise
each part keeps the task's.

- Each part is a task in its own right: on the lists and displays, nudged, counted for
  capacity and in "too much today" (O1a), so a low-energy day can offer just one part.
- The original stays as the parent, off every list and display while its parts stand in
  for it (`NOT_SPLIT` in the task queries, and `off_displays`). Each part says where it
  stands ("part 2 of 3 of Split Merlin's cat box; 1 of 3 parts done").
- When the last part is settled, the parent is checked off on its own: done if any part
  was done, taken off the list if every part was.
- A repeating chore's steps aren't split (its schedule is its own): refused, saying so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from themi import clock
from themi.accounts import Member, NotFound
from themi.core import groups, keys
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi.standard.tasks import Task, TaskBoard, TaskChange

log = logging.getLogger(__name__)

MAX_TITLE = 120
WHO = ("me", "partner", "either", "")


@dataclass(frozen=True)
class Part:
    step: int  # 1-based, as people count
    who: str  # 'me', 'partner', 'either' or '' (the task's assignee)
    due_on: date | None


def part_title(parent: str, step: str) -> str:
    """ "Split Merlin's cat box: Scoop the old litter", so each part reads on its own (a
    display shows titles alone)."""
    return f"{parent}: {step}"[:MAX_TITLE]


def part_effort(effort: int, parts: int) -> int:
    return max(1, round(effort / parts))


class TaskParts:
    def __init__(self, board: TaskBoard) -> None:
        self.board = board
        self.services = board.services
        self.store = board.store
        self.db = board.db

    def install(self) -> None:
        self.services.provide(keys.task_parts, self)
        self.board.change_listeners.append(self._changed)
        self.board.display_notes.append(self.note)

    # ----- reading ------------------------------------------------------------------

    def parts(self, parent_id: int) -> list[Task]:
        rows = self.db.query(
            "SELECT task_id FROM task_parts WHERE parent_id = ? ORDER BY position", (parent_id,)
        )
        return [self.board.get(r["task_id"]) for r in rows]

    def parent_of(self, task_id: int) -> Task | None:
        parent = self.db.scalar("SELECT parent_id FROM task_parts WHERE task_id = ?", (task_id,))
        return self.board.get(parent) if parent is not None else None

    def progress(self, parent_id: int) -> tuple[int, int]:
        """(parts done, parts in all)."""
        parts = self.parts(parent_id)
        return sum(p.status == "done" for p in parts), len(parts)

    def note(self, task: Task) -> str | None:
        """A part's place, for the open items and the website: "Part 2 of 3 of Split
        Merlin's cat box; 1 of 3 parts done." """
        row = self.db.one(
            "SELECT parent_id, position FROM task_parts WHERE task_id = ?", (task.id,)
        )
        if row is None:
            return None
        parent = self.board.get(row["parent_id"])
        done, total = self.progress(parent.id)
        return f"Part {row['position']} of {total} of {parent.title}; {done} of {total} parts done."

    # ----- splitting ----------------------------------------------------------------

    async def split(self, task: Task, by: Member, chosen: list[Part]) -> list[Task]:
        """Every step becomes a part: the chosen ones as they say, the rest staying with
        the task's assignee. ToolDeclined says why it can't be."""
        if task.status not in ("open", "snoozed"):
            raise ToolDeclined(f"{task.title} is settled already; there's nothing to split.")
        if task.repeats:
            raise ToolDeclined(
                f"{task.title} repeats, and a repeating chore's steps aren't split: its "
                "schedule is its own. Nothing was changed."
            )
        if self.parts(task.id):
            raise ToolDeclined(f"{task.title} is split already. Nothing was changed.")
        if self.parent_of(task.id) is not None:
            raise ToolDeclined(f"{task.title} is a part already. Nothing was changed.")
        if len(task.steps) < 2:
            raise ToolDeclined(
                f"{task.title} has {'one step' if task.steps else 'no steps'}, so there's "
                "nothing to split. Nothing was changed."
            )
        by_step: dict[int, Part] = {}
        for part in chosen:
            if not 1 <= part.step <= len(task.steps):
                raise ToolFailed(
                    f"{task.title} has {len(task.steps)} steps; there's no step {part.step}."
                )
            if part.who not in WHO:
                raise ToolFailed(f"who is one of {', '.join(repr(w) for w in WHO)}.")
            by_step[part.step] = part
        made = []
        for number, step in enumerate(task.steps, start=1):
            part = by_step.get(number, Part(number, "", None))
            made.append(await self._make(task, by, number, step, part))
        self.db.execute("UPDATE tasks SET off_displays = 1 WHERE id = ?", (task.id,))
        if task.status == "snoozed":
            self.db.execute(
                "UPDATE tasks SET status = 'open', snoozed_until = NULL WHERE id = ?", (task.id,)
            )
        self.board.withdraw_prompt(task)
        await self.board._changed(self.board.get(task.id), "split", True)
        return made

    async def _make(self, parent: Task, by: Member, number: int, step: str, part: Part) -> Task:
        assignee = self._assignee(parent, by, part.who)
        made = await self.board.create(
            by,
            part_title(parent.title, step),
            parent.kind,
            part_effort(parent.effort, len(parent.steps)),
            part.due_on or parent.due_on,
            interactive=True,
            assignee=assignee,
            due_time=parent.due_time if part.due_on is None else None,
            importance=parent.importance,
        )
        self.db.execute(
            "INSERT INTO task_parts (task_id, parent_id, position) VALUES (?, ?, ?)",
            (made.id, parent.id, number),
        )
        return made

    def _assignee(self, parent: Task, by: Member, who: str) -> Member | None:
        """None lets matching decide (either of you: whoever has room)."""
        if who == "me":
            return by
        if who == "partner":
            others = [m for m in self.store.list_members() if m.id != by.id]
            if len(others) != 1:
                raise ToolFailed("Name who should do it; 'partner' fits a household of two.")
            return others[0]
        if who == "either" or parent.assignee is None:
            return None
        return self.store.get_member(parent.assignee)

    # ----- settling -----------------------------------------------------------------

    async def _changed(self, task: Task, change: TaskChange, interactive: bool) -> None:
        if change not in ("done", "cancelled"):
            return
        parent = self.parent_of(task.id)
        if parent is None or parent.status not in ("open", "snoozed"):
            return
        parts = self.parts(parent.id)
        if any(p.status in ("open", "snoozed") for p in parts):
            return
        if any(p.status == "done" for p in parts):
            self.db.execute(
                "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
                (to_utc_iso(clock.now()), parent.id),
            )
            await self.board._changed(self.board.get(parent.id), "done", interactive)
        else:
            await self.board.cancel(parent.id, self._settler(task), interactive=interactive)

    def _settler(self, task: Task) -> Member:
        if task.assignee is not None:
            return self.store.get_member(task.assignee)
        return next(m for m in self.store.list_members() if m.is_admin)


def _parts_of(args: dict[str, Any]) -> list[Part]:
    chosen = []
    for item in args.get("parts") or []:
        due = str(item.get("due") or "").strip()
        try:
            due_on = date.fromisoformat(due) if due else None
        except ValueError as exc:
            raise ToolFailed(f"'{due}' isn't a date like 2026-11-10.") from exc
        chosen.append(Part(int(item.get("step") or 0), str(item.get("who") or ""), due_on))
    return chosen


@tool(
    "split_task",
    "Split a one-off task's steps into tasks of their own, which can be done apart or by "
    "different people ('split the cat box up', 'I'll do the first part', 'give her the last "
    "step'). Every step becomes a part; parts: only the steps they named, each with who "
    "('me', 'partner', 'either' for whoever has room, '' to stay with the task's assignee) "
    "and due ('YYYY-MM-DD' or '' for the task's). The task is checked off when its last part "
    "is. Not for a repeating chore.",
    {
        "task_id": {"type": "integer"},
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {"type": "integer", "description": "1 for the first step"},
                    "who": {"type": "string", "enum": list(WHO)},
                    "due": {"type": "string"},
                },
                "required": ["step", "who", "due"],
            },
        },
    },
)
async def split_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    parts = ctx.services.maybe(keys.task_parts)
    assert parts is not None
    try:
        task = parts.board.get(int(args["task_id"]))
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    made = await parts.split(task, ctx.member, _parts_of(args))
    names = {m.id: m.name for m in ctx.services.store.list_members()}
    lines = [
        f"- {p.title} ({'them' if p.assignee == ctx.member.id else names.get(p.assignee or 0, '')}"
        f"{', due ' + p.due_on.isoformat() if p.due_on else ''})"
        for p in made
    ]
    return (
        f"Split {task.title} into {len(made)} parts, each a task of its own:\n"
        + "\n".join(lines)
        + "\nIt's checked off when the last part is done. Say who has which part, briefly."
    )


class TaskPartsModule(Module):
    """F26c: a task's steps split into tasks of their own."""

    name = "task_parts"
    title = "Task parts"
    summary = "Splits a task's steps into tasks of their own, to share or spread out."
    requires = ("tasks",)
    tool_groups = (groups.SCHEDULES,)

    def install(self, ctx: ModuleContext) -> None:
        ctx.provide(TaskParts(ctx.get(TaskBoard))).install()
        ctx.tool(split_task)
