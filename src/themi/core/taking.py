"""Tasks of a partner's that someone could take on (F29f, bug #147).

"What tasks from Erin could I take to make her day easier?" staged "Erin's tasks" as a
morning routine on the wall. It's F22a's question about the partner, with a hand-over:
her open one-off tasks that someone else could do, each with a "Take it" button. A tap
gives it to whoever asked, and Erin hears once, at a good moment, who took it.

Not offered: repeating chores (taking one hands over every round), medicine, check-ins
and exercise plans (they're hers by nature), and anything already on both lists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.tasks import TaskBoard
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.modules import Module, ModuleContext

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.core.tasks import Task, TaskBoard

KIND = "take_task"  # the button kind
MAX_OFFERED = 5
LABEL_LIMIT = 40
OFFER_TEXT = "{name}'s open tasks you could take:\n{lines}\nTap one to take it."
NONE_TEXT = "Nothing of {name}'s right now that someone else could take."
TOOK_TEXT = "{title} is yours now. Thanks for taking it."
GONE_TEXT = "{title} isn't {name}'s to hand over any more."
TOLD_TEXT = "{taker} took {title} off your list."


def can_take(task: Task, owner: Member) -> bool:
    return (
        task.assignee == owner.id
        and task.status in ("open", "snoozed")
        and not task.shared
        and not task.either
        and not task.repeats
        and not task.medicine
        and not task.check_in
        and task.progression is None
    )


class Taking:
    def __init__(self, services: Services, board: TaskBoard) -> None:
        self.services = services
        self.board = board
        self.store = services.store

    def install(self) -> None:
        self.services.provide(keys.taking, self)
        self.services.tools.register(tasks_i_could_take)
        self.services.button_handlers[KIND] = self.on_button

    def offered(self, owner: Member) -> list[Task]:
        return [t for t in self.board.open_for(owner) if can_take(t, owner)][:MAX_OFFERED]

    async def offer(self, taker: Member, owner: Member) -> str:
        """The list, with a button per task, sent as the answer."""
        tasks = self.offered(owner)
        if not tasks:
            text = NONE_TEXT.format(name=owner.name)
            await self.services.outbox.send(taker, text, priority=Priority.REPLY)
            return text
        lines = "\n".join(f"- {t.title}" for t in tasks)
        text = OFFER_TEXT.format(name=owner.name, lines=lines)
        buttons = [
            Button(f"Take: {_short(t.title)}", KIND, {"task": t.id, "owner": owner.id})
            for t in tasks
        ]
        await self.services.outbox.send(taker, text, priority=Priority.REPLY, buttons=buttons)
        return text

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        payload: dict[str, Any] = event.button.payload
        taker = event.member
        owner = self.store.get_member(int(payload.get("owner", 0)))
        task = self.board.get(int(payload.get("task", 0)))
        if not can_take(task, owner) or owner.id == taker.id:
            await self.services.outbox.send(
                taker, GONE_TEXT.format(title=task.title, name=owner.name), priority=Priority.REPLY
            )
            return
        await self.board.reassign(task.id, taker)
        await self.services.outbox.send(
            taker, TOOK_TEXT.format(title=task.title), priority=Priority.REPLY
        )
        await self.services.outbox.send(  # once, gently, at a good moment for them
            owner,
            TOLD_TEXT.format(taker=taker.name, title=task.title),
            priority=Priority.LOW,
            kind="task_taken",
            dedupe_key=f"task-taken:{task.id}",
        )


def _short(title: str) -> str:
    return title if len(title) <= LABEL_LIMIT else title[: LABEL_LIMIT - 1].rstrip() + "…"


@tool(
    "tasks_i_could_take",
    "When someone asks which of their partner's tasks they could take, do or help with "
    "('what could I take off Erin's plate?', 'which of her tasks can I do?'): their "
    "partner's open one-off tasks, each with a button to take it, sent as the answer. "
    "Never a routine, a list or a new task.",
    {},
)
async def tasks_i_could_take(ctx: ToolContext, args: dict[str, Any]) -> str:
    taking = ctx.services.maybe(keys.taking)
    if taking is None:
        raise ToolFailed("Tasks aren't set up.")
    others = [m for m in ctx.services.store.list_members() if m.id != ctx.member.id]
    if len(others) != 1:
        raise ToolFailed("Whose tasks? Ask which of the family they mean.")
    text = await taking.offer(ctx.member, others[0])
    ctx.cards.append(text)
    return f"Sent them this, with a Take button on each task: {text}"


class TakingModule(Module):
    """Taking a task on, from the other person or the chart."""

    name = "taking"
    requires = ("tasks",)

    def install(self, ctx: ModuleContext) -> None:
        ctx.provide(Taking(ctx.services, ctx.get(TaskBoard))).install()
