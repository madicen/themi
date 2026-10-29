"""Follow-ups: a reminder that comes once a task is done (F17b, Erin's bug #70).

"Immediately after I indicate that I cleaned the bird cage, remind me to refill the water
and replace the food bowls" became a task due the next day. Now it's a follow-up of the
bird cage: nothing until that's done (in chat, with a button, or ticked on the wall), then
a task is made from it and nudged at once (straight away when they're in the chat, else
inside quiet hours and the daily limit). A repeating task's follow-up comes back every
round; a one-off's goes once. A follow-up is Themi's own reminder, so never on the wall.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member, NotFound
from themi.channels.outbox import Priority
from themi.core.prompts import OpenItem
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.core.tasks import Task, TaskBoard

log = logging.getLogger(__name__)

# Never "straight away" or "right away": the PDA shield reads those as pressure.
SAVED_TEXT = '"{title}" comes up as soon as "{after}" is done{each}.'
EACH_ROUND = ", every time"
REMOVED_TEXT = 'No follow-up after "{after}" any more.'


class FollowUps:
    def __init__(self, services: Services, board: TaskBoard) -> None:
        self.services = services
        self.board = board
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.follow_ups = self
        s.tools.register(add_follow_up)
        s.tools.register(remove_follow_up)
        s.open_item_sources.append(self.open_items)
        self.board.done_hooks.append(self.on_done)
        self.board.change_listeners.append(self.on_task_changed)

    def add(
        self, after: Task, member: Member, title: str, steps: list[str], by: Member
    ) -> dict[str, Any]:
        cur = self.db.execute(
            "INSERT INTO task_follow_ups (after_task, member_id, created_by, title, steps, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (after.id, member.id, by.id, title, json.dumps(steps), to_utc_iso(clock.now())),
        )
        row = self.db.one("SELECT * FROM task_follow_ups WHERE id = ?", (cur,))
        assert row is not None
        return row

    def of(self, task_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM task_follow_ups WHERE after_task = ? ORDER BY id", (task_id,)
        )

    def remove(self, task_id: int) -> int:
        count = len(self.of(task_id))
        self.db.execute("DELETE FROM task_follow_ups WHERE after_task = ?", (task_id,))
        return count

    async def on_done(self, task: Task, by: Member, interactive: bool) -> None:
        """Its task is done: each follow-up becomes a task, nudged now."""
        store = self.services.store
        for row in self.of(task.id):
            member = store.get_member(row["member_id"])
            if row["last_task"] is not None and self._still_open(row["last_task"]):
                continue  # the last one is still waiting for them: not a second
            made = await self.board.create(
                store.get_member(row["created_by"]) if row["created_by"] else member,
                row["title"],
                "physical",
                1,
                self.board._today(),
                assignee=member,
                steps=json.loads(row["steps"]),
                nudge=False,
                off_wall=True,  # Themi's own reminder, like a check-in (bug #41)
            )
            self.db.execute(
                "UPDATE task_follow_ups SET last_task = ? WHERE id = ?", (made.id, row["id"])
            )
            # In the chat now (they just said or tapped it): straight away. Otherwise, as
            # soon as quiet hours and the daily limit allow.
            here = interactive and by.id == member.id
            await self.board.prompt(made, priority=Priority.REPLY if here else Priority.NORMAL)
        if not task.repeats or self.board.get(task.id).status == "done":
            self.db.execute("DELETE FROM task_follow_ups WHERE after_task = ?", (task.id,))

    async def on_task_changed(self, task: Task, change: str, interactive: bool) -> None:
        if change == "cancelled":  # nothing to follow any more
            self.db.execute("DELETE FROM task_follow_ups WHERE after_task = ?", (task.id,))

    def _still_open(self, task_id: int) -> bool:
        try:
            return self.board.get(task_id).status in ("open", "snoozed")
        except NotFound:
            return False

    def open_items(self, member: Member) -> list[OpenItem]:
        items = []
        for row in self.db.query(
            "SELECT * FROM task_follow_ups WHERE member_id = ? ORDER BY id", (member.id,)
        ):
            after = self.board.get(row["after_task"])
            each = EACH_ROUND if after.repeats else ""
            items.append(
                OpenItem(
                    f'Follow-up: "{row["title"]}" comes up as soon as "{after.title}" is '
                    f"done{each} (no date of its own)."
                )
            )
        return items


def _follow_ups(ctx: ToolContext) -> FollowUps:
    follow_ups = ctx.services.follow_ups
    if follow_ups is None:
        raise ToolFailed("Follow-ups aren't set up.")
    return follow_ups


@tool(
    "add_follow_up",
    "A reminder that comes once another task is done, not at a time: 'right after I clean "
    "the bird cage, remind me to refill the water'. after_task_id: the task it follows (from "
    "the open items). It has no date; it's nudged as soon as that task is done, every time "
    "for a repeating one. Never a separate dated task for this.",
    {
        "after_task_id": {"type": "integer"},
        "title": {"type": "string", "description": "What to do then, in their words."},
        "steps": {"type": "array", "items": {"type": "string"}},
    },
)
async def add_follow_up(ctx: ToolContext, args: dict[str, Any]) -> str:
    follow_ups = _follow_ups(ctx)
    try:
        after = follow_ups.board.get(args["after_task_id"])
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    if after.status not in ("open", "snoozed"):
        raise ToolFailed(f'"{after.title}" is done already, so there\'s nothing to follow.')
    title = " ".join(str(args["title"]).split()).rstrip(".")[:200]
    if not title:
        raise ToolFailed("What should the follow-up say?")
    steps = [" ".join(str(s).split()) for s in args["steps"] if str(s).strip()]
    follow_ups.add(after, ctx.member, title, steps, ctx.member)
    each = EACH_ROUND if after.repeats else ""
    return "Saved. " + SAVED_TEXT.format(after=after.title, title=title, each=each)


@tool(
    "remove_follow_up",
    "Stop the follow-up reminders that come after a task is done. after_task_id: that task.",
    {"after_task_id": {"type": "integer"}},
)
async def remove_follow_up(ctx: ToolContext, args: dict[str, Any]) -> str:
    follow_ups = _follow_ups(ctx)
    try:
        after = follow_ups.board.get(args["after_task_id"])
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    if not follow_ups.remove(after.id):
        raise ToolFailed(f'"{after.title}" has no follow-up.')
    return REMOVED_TEXT.format(after=after.title)
