"""When it's too much (O1a, Erin's idea #94): a few things for now, and the rest kept.

For anyone who gives a sign of being overwhelmed, in any words. The message's own words
("overwhelmed", "too much", "pare it down"...) put a line in the turn's context, and
`focus_now` is a core tool, so the model has it whatever the router chose. The morning list
has a "Too much today" button, too.

`focus_now` picks at most three of today's open things (due or overdue, not put off or
waiting for the chart; what the day summary has): medicines always, then ones with a time
today, then urgent and important (T1), then the lightest. One message: those few, and a
line that the rest are kept. Never energy, never "should".

The rest (O1b) can be spread over the next two weeks, the most pressing first, each to the
first day with room under a budget: the person's setting, or what they usually get done in
a day (the median of the last four weeks, 2 to 8; 4 with nothing to go by). It's offered
with [Spread them out] [Leave them for now], or done at once when they asked for the rest
to be moved. Medicines and deadline chores stay. A repeating chore goes to its next round
rather than stack on a day. A task on both lists is put off for them alone (F19c), to
that day's morning, so the other still has it.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import priority
from themi.core.repeat import next_occurrences
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
SPREAD_TEXT = "The rest are spread out, no more than {budget} on a day:"
STAY_TEXT = "Staying with today, as they can't move: {titles}."
LEFT_TEXT = "The other {n} stay where they are; nothing's dropped."
LEFT_ONE_TEXT = "The other one stays where it is; nothing's dropped."
SPREAD_BUTTON = "Spread them out"
LEAVE_BUTTON = "Leave them for now"
LOOK_AHEAD = 14  # days the rest can be spread over
HISTORY = timedelta(days=28)  # what usually gets done in a day, from these weeks
USUAL_DAY = 4  # with nothing done yet to go by
BUDGET_RANGE = (2, 8)
MORNING = time(9)  # a shared task put off to a day comes back to them then


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

    def text(self, member: Member, few: list[Task], rest: list[Task], after: str = "") -> str:
        """The few, then `after` (what became of the rest), or that the rest are kept."""
        if not few:
            return CLEAR_TEXT
        today = self.summary.today()
        lines = []
        for task in few:
            at = self.board.time_of(task, today)
            lines.append(f"- {clock_words(at)}: {task.title}" if at else f"- {task.title}")
        these = "this" if len(few) == 1 else "these"
        text = FOCUS_TEXT.format(these=these, items="\n".join(lines))
        if after:
            return f"{text}\n{after}"
        if not rest:
            return f"{text}\n{ALL_TEXT}"
        kept = KEPT_ONE_TEXT if len(rest) == 1 else KEPT_TEXT.format(n=len(rest))
        return f"{text}\n{kept}"

    async def send(self, member: Member, *, spread: bool = False) -> str:
        """The few for now; the rest spread out at once (`spread`), or offered to be."""
        buttons: list[Button] = []
        if spread:
            text = await self.spread_now(member)
        else:
            few, rest = self.pick(member)
            text = self.text(member, few, rest)
            if few and rest:
                buttons = [
                    Button(SPREAD_BUTTON, "focus", {"action": "spread"}),
                    Button(LEAVE_BUTTON, "focus", {"action": "leave"}),
                ]
        await self.services.outbox.send(
            member, text, priority=Priority.REPLY, kind="focus", buttons=buttons
        )
        return text

    async def on_button(self, event: InboundEvent) -> None:
        """ "Too much today" on the morning list; then Spread them out, or Leave them."""
        assert event.button is not None
        member = self.services.store.get_member(event.member.id)
        action = event.button.payload.get("action")
        if action == "focus":
            await self.send(member)
            return
        if action == "spread":
            text = await self.spread_now(member)
        else:
            few, rest = self.pick(member)
            left = LEFT_ONE_TEXT if len(rest) == 1 else LEFT_TEXT.format(n=len(rest))
            text = self.text(member, few, rest, left if rest else "")
        if event.button.message_id is not None:
            await self.services.outbox.edit(member, event.button.message_id, text)

    # ----- the rest, spread out (O1b) -----------------------------------------------------

    def budget(self, member: Member) -> int:
        """At most this many on a day: their setting, else what they usually get done."""
        if member.day_budget:
            return member.day_budget
        tz, today = self._tz(), self.summary.today()
        midnight = datetime(today.year, today.month, today.day, tzinfo=tz)
        done = self.board.done_between(member, midnight - HISTORY, midnight)
        per_day = Counter(d.at.astimezone(tz).date() for d in done)
        if not per_day:
            return USUAL_DAY
        low, high = BUDGET_RANGE
        return min(max(int(statistics.median(per_day.values())), low), high)

    async def spread_now(self, member: Member) -> str:
        """The few for now, and the rest moved to the coming days, said by day."""
        few, rest = self.pick(member)
        if not rest:
            return self.text(member, few, rest)
        budget = self.budget(member)
        today = self.summary.today()
        days = [today + timedelta(days=n) for n in range(1, LOOK_AHEAD + 1)]
        load = {d: len(self.summary.due(member, d)) for d in days}  # before anything moves
        placed: dict[date, list[str]] = {}
        stays = []
        for task in rest:  # most pressing first, so they get the nearest days
            if task.medicine or task.due_before_task is not None:
                stays.append(task.title)
                continue
            day = self._next_round(task, today) if not task.shared else None
            if day is None:
                day = next((d for d in days if load[d] < budget), min(days, key=load.__getitem__))
            if task.shared:  # theirs alone: on the other's list it stays as it is
                at = datetime(day.year, day.month, day.day, MORNING.hour, tzinfo=self._tz())
                self.board.snooze(task.id, until=at, by=member)
            else:
                await self.board.reschedule(task.id, day, interactive=True)
            load[day] = load.get(day, 0) + 1
            placed.setdefault(day, []).append(task.title)
        lines = [SPREAD_TEXT.format(budget=budget)] if placed else []
        lines += [f"- {d:%a %d %b}: {', '.join(placed[d])}" for d in sorted(placed)]
        if stays:
            lines.append(STAY_TEXT.format(titles=", ".join(stays)))
        return self.text(member, few, rest, "\n".join(lines))

    def _next_round(self, task: Task, today: date) -> date | None:
        """A repeating chore's next round after today: it goes there rather than stack."""
        if task.repeat is None:
            return None
        tz = self._tz()
        end = datetime(today.year, today.month, today.day, tzinfo=tz) + timedelta(
            days=1, seconds=-1
        )
        found = next_occurrences(task.repeat, end, tz)
        return found[0].date() if found else None

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


@tool(
    "focus_now",
    "When someone sounds overwhelmed, in any words ('it's too much', 'I can't do all this', "
    "'pare today down', 'I'm drowning'): a few of today's things for now (three at most, "
    "medicines always), and a line that the rest are kept, with an offer to spread them over "
    "the coming days. spread: true only when they asked for the rest to be moved ('move the "
    "rest', 'snooze everything else'): then it's done at once, never more on a day than "
    "they usually manage. It's sent to them as it is: don't list the tasks again; a short "
    "kind line at most. Never mention energy.",
    {"spread": {"type": "boolean"}},
)
async def focus_now(ctx: ToolContext, args: dict[str, Any]) -> str:
    focus = ctx.services.focus
    if focus is None:
        raise ToolFailed("This isn't set up.")
    text = await focus.send(ctx.member, spread=bool(args["spread"]))
    ctx.answered.append("focus_now")
    return (
        "Sent to them already, word for word:\n"
        f"{text}\n"
        "Don't repeat it: a short kind line at most, or nothing."
    )
