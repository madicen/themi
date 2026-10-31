"""When it's too much (O1a, Erin's idea #94): a few things for now, and the rest kept.

For anyone who gives a sign of being overwhelmed, in any words. The message's own words
("overwhelmed", "too much", "pare it down"...) put a line in the turn's context, and
`focus_now` is a core tool, so the model has it whatever the router chose. The morning list
has a "Too much today" button, too.

`focus_now` picks at most three of today's open things (due or overdue, not put off or
waiting for the chart; what the day summary has): medicines always, then ones with a time
today, then urgent and important (T1), then the lightest. One message: those few, and a
line that the rest are kept. Never energy, never "should".
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.channels.events import InboundEvent
from themi.channels.outbox import Priority
from themi.core import priority
from themi.core.tasks import Task, TaskBoard, clock_words
from themi.core.tools import ToolContext, ToolFailed, tool

if TYPE_CHECKING:
    from themi.core.day_summary import DaySummary
    from themi.core.services import Services

AT_MOST = 3
OVERWHELM = re.compile(
    r"\b(?:overwhelm\w*|too much (?:on|to do|today|going on|right now)|"
    r"(?:it'?s|this is|that'?s|everything'?s|all) (?:just )?too much|"
    r"can'?t (?:keep up|cope|do it all|handle (?:it|this|all))|"
    r"pare (?:it|things|this|today|them|that) down|pared down|"
    r"swamped|drowning|snowed under|burn(?:ed|t) out|frazzled|"
    r"so much to do|too many things|stressed out|behind on everything)",
    re.IGNORECASE,
)
SIGNAL = (
    "they sound overwhelmed. focus_now sends a few things for now and keeps the rest; "
    "use it unless they're asking for something else"
)
FOCUS_TEXT = "For now, just {these}:\n{items}"
KEPT_TEXT = "The other {n} are kept; nothing's dropped."
KEPT_ONE_TEXT = "The other one is kept; nothing's dropped."
ALL_TEXT = "That's all there is for today."
CLEAR_TEXT = "Nothing's due today. All clear."


def overwhelmed(text: str) -> bool:
    """Words that say it's too much, from anyone."""
    return bool(OVERWHELM.search(text))


class Focus:
    def __init__(self, services: Services, board: TaskBoard, summary: DaySummary) -> None:
        self.services = services
        self.board = board
        self.summary = summary

    def install(self) -> None:
        self.services.focus = self
        self.services.tools.register(focus_now)
        self.services.button_handlers["focus"] = self.on_button

    def pick(self, member: Member) -> tuple[list[Task], list[Task]]:
        """Today's few for now, and the rest: medicines, a time today, urgent and important,
        then the lightest."""
        today = self.summary.today()
        now = clock.now()

        def order(task: Task) -> tuple[Any, ...]:
            return (
                not task.medicine,
                self.board.time_of(task, today) is None,
                priority.rank(task, today, now, now),
                task.effort,
                task.id,
            )

        due = sorted(self.summary.due(member, today), key=order)
        medicines = [t for t in due if t.medicine]
        cut = max(AT_MOST, len(medicines))
        return due[:cut], due[cut:]

    def text(self, member: Member, few: list[Task], rest: list[Task]) -> str:
        if not few:
            return CLEAR_TEXT
        today = self.summary.today()
        lines = []
        for task in few:
            at = self.board.time_of(task, today)
            lines.append(f"- {clock_words(at)}: {task.title}" if at else f"- {task.title}")
        these = "this" if len(few) == 1 else "these"
        text = FOCUS_TEXT.format(these=these, items="\n".join(lines))
        if not rest:
            return f"{text}\n{ALL_TEXT}"
        kept = KEPT_ONE_TEXT if len(rest) == 1 else KEPT_TEXT.format(n=len(rest))
        return f"{text}\n{kept}"

    async def send(self, member: Member) -> str:
        few, rest = self.pick(member)
        text = self.text(member, few, rest)
        await self.services.outbox.send(member, text, priority=Priority.REPLY, kind="focus")
        return text

    async def on_button(self, event: InboundEvent) -> None:
        """ "Too much today" on the morning list."""
        await self.send(self.services.store.get_member(event.member.id))


@tool(
    "focus_now",
    "When someone sounds overwhelmed, in any words ('it's too much', 'I can't do all this', "
    "'pare today down', 'I'm drowning'): a few of today's things for now (three at most, "
    "medicines always), and a line that the rest are kept. It's sent to them as it is: "
    "don't list the tasks again; a short kind line at most. Never mention energy.",
    {},
)
async def focus_now(ctx: ToolContext, args: dict[str, Any]) -> str:
    focus = ctx.services.focus
    if focus is None:
        raise ToolFailed("This isn't set up.")
    text = await focus.send(ctx.member)
    ctx.answered.append("focus_now")
    return (
        "Sent to them already, word for word:\n"
        f"{text}\n"
        "Don't repeat it: a short kind line at most, or nothing."
    )
