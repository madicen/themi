"""A step-up plan as a picture (DC11; the Day Card Plan's "Other uses").

The weeks of a plan like Erin's runs ("1.3 miles, then 1.5, then up 0.25 a week, on
Tuesdays", F9c) as bars that step up: a few weeks back, this week marked, the weeks ahead,
and where it stops going up. It shows the plan and nothing else: never what was done or
missed. "show my run plan" (`show_step_plan`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from themi.core import keys
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.drawing.svg import write_svg
from themi.drawing.text import fit
from themi.standard.day_card import THEMES
from themi.standard.drawings import DrawingsPreferences
from themi.standard.progression import Progression, read_back

WIDTH, HEIGHT = 840, 440
PNG_WIDTH = 1680
PAD = 28
BEFORE, AFTER = 3, 8  # weeks shown either side of this one
CAPTION = "Your plan, week by week."


def _number(value: float) -> str:
    return f"{value:g}"


@dataclass(frozen=True)
class Week:
    starts: date
    amount: float
    now: bool = False


@dataclass(frozen=True)
class PlanCardData:
    title: str
    unit: str
    weeks: tuple[Week, ...]
    up_to: float | None
    words: str  # the plan read back, as Themi says it


def plan_weeks(plan: Progression, today: date) -> PlanCardData:
    this_week = plan.week_of(max(today, plan.start))
    first = max(plan.start, this_week - timedelta(weeks=BEFORE))
    weeks = []
    for n in range(BEFORE + AFTER + 1):
        starts = first + timedelta(weeks=n)
        amount = plan.amount_on(starts)
        if amount is not None:
            weeks.append(Week(starts, amount, starts == this_week and today >= plan.start))
    return PlanCardData("", plan.unit, tuple(weeks), plan.up_to, read_back(plan))


def view(data: PlanCardData, theme: str = "light") -> dict[str, Any]:
    colors = THEMES[theme]
    x0, x1 = PAD + 8.0, WIDTH - PAD - 8.0
    top, bottom = 130.0, HEIGHT - 70.0
    most = max([w.amount for w in data.weeks] + [data.up_to or 0.0, 0.1])
    gap = 10.0
    count = max(len(data.weeks), 1)
    width = (x1 - x0 - gap * (count - 1)) / count

    def y(amount: float) -> float:
        return bottom - amount / most * (bottom - top)

    bars = []
    for i, week in enumerate(data.weeks):
        x = x0 + i * (width + gap)
        bars.append(
            {
                "x": x,
                "mid": x + width / 2,
                "y": y(week.amount),
                "width": width,
                "height": bottom - y(week.amount),
                "label": _number(week.amount),
                "week": f"{week.starts.day} {week.starts:%b}",
                "now": week.now,
            }
        )
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "pad": PAD,
        "c": colors,
        "title": fit(data.title, 22, WIDTH - 2 * PAD, bold=True),
        "words": fit(f"{data.words[0].upper()}{data.words[1:]}", 13, WIDTH - 2 * PAD),
        "unit": data.unit,
        "bars": bars,
        "bottom": bottom,
        "x0": x0,
        "x1": x1,
        "cap_y": y(data.up_to) if data.up_to else None,
        "cap": f"up to {_number(data.up_to)} {data.unit}" if data.up_to else "",
    }


def plan_svg(data: PlanCardData, theme: str = "light") -> str:
    return write_svg("plan_card.svg", **view(data, theme))


@tool(
    "show_step_plan",
    "Sends them a picture of a task's step-up plan (set with set_task_plan): its amount "
    "week by week, this week marked. For 'show my run plan', 'how does my plan go up?'. "
    "task_id is the task's number. It's sent as it is: don't repeat it.",
    {"task_id": {"type": "integer"}},
)
async def show_step_plan(ctx: ToolContext, args: dict[str, Any]) -> str:
    from themi.channels.outbox import Priority

    board = ctx.services.maybe(keys.taskboard)
    if board is None:
        raise ToolFailed("Tasks aren't set up.")
    try:
        task = board.get(int(args["task_id"]))
    except Exception as exc:
        raise ToolFailed("There's no task with that number.") from exc
    if task.progression is None:
        raise ToolDeclined(f"{task.title} has no step-up plan. Say so; set_task_plan makes one.")
    data = plan_weeks(task.progression, board._today())
    data = PlanCardData(task.title, data.unit, data.weeks, data.up_to, data.words)
    drawings = ctx.services.maybe(keys.drawings)
    if drawings is not None:
        theme = ctx.services.store.preferences(ctx.member.id, DrawingsPreferences).picture_theme
        png = await drawings.png(plan_svg(data, theme), PNG_WIDTH)
        if png is not None and await ctx.services.outbox.send_photo(
            ctx.member, png, CAPTION, kind="plan"
        ):
            ctx.answered.append("show_step_plan")
            return "Sent the plan as a picture. Don't repeat it."
    week = task.progression.words_on(board._today())
    text = f"{task.title}: {data.words}." + (f" Now: {week}." if week else "")
    await ctx.services.outbox.send(ctx.member, text, priority=Priority.REPLY, kind="plan")
    ctx.answered.append("show_step_plan")
    return "Sent the plan in words. Don't repeat it."
