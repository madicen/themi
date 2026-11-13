"""Pictures of a person's tasks and of their routines (F42g, Michael's bug #206: "should be
able to ask for tasks, routines, maybe everything and get a graphic"), and today's day card
on request. The Day Card Plan's "Other uses" didn't have these; this adds them.

A list card is a title, a date line and sections, each a heading over rows. A row is
words, a short note ("was due Tue", "shared") and, for a routine's items, a tick when done.
Long lists are cut with "and N more", never crammed. No energy, and no count of misses.

- Tasks (`show_tasks_picture`): their open tasks as the morning list orders them: overdue
  first (with when it was due), then today, then the next few days, then any time.
- Routines (`show_routines_picture`): each routine with something on it that day, its
  window under its name, each item with a tick when done (today only).
- The day (`show_day`): the morning picture, today's day card (DC3), on request.

Each is sent as a picture when drawings work, and in words when they don't.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from themi.accounts import Member
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.drawing.svg import write_svg
from themi.drawing.text import fit
from themi.standard.day_card import THEMES
from themi.standard.drawings import DrawingsPreferences

WIDTH = 540
PNG_WIDTH = 1080
PAD = 28
ROW = 30  # px a row takes
HEAD = 34  # px a section's heading takes
MOST = 14  # rows a card shows; the rest are counted
SOON_DAYS = 3  # "the next few days"
TASKS_CAPTION = "Your tasks."
ROUTINES_CAPTION = "Your routines."
DAY_CAPTION = "Your day."
NO_TASKS_TEXT = "Nothing open on your list."
NO_ROUTINES_TEXT = "Nothing on your routines {which}."


@dataclass(frozen=True)
class Row:
    text: str
    note: str = ""
    done: bool | None = None  # None: no tick box (a task); True/False: a routine's item


@dataclass(frozen=True)
class Section:
    heading: str
    rows: tuple[Row, ...]
    note: str = ""  # beside the heading: a routine's window


@dataclass(frozen=True)
class ListCardData:
    title: str
    day: date
    sections: tuple[Section, ...]


def view(data: ListCardData, theme: str = "light") -> dict[str, Any]:
    colors = THEMES[theme]
    y = 104.0
    sections = []
    shown = 0
    total = sum(len(s.rows) for s in data.sections)
    for section in data.sections:
        if shown >= MOST:
            break
        rows = []
        head_y = y
        y += HEAD
        for row in section.rows:
            if shown >= MOST:
                break
            box = row.done is not None
            room = WIDTH - 2 * PAD - (28 if box else 0) - (120 if row.note else 0)
            rows.append(
                {
                    "y": y,
                    "text": fit(row.text, 15, room),
                    "note": fit(row.note, 12, 116),
                    "box": box,
                    "done": bool(row.done),
                }
            )
            y += ROW
            shown += 1
        sections.append(
            {"y": head_y, "heading": section.heading, "note": section.note, "rows": rows}
        )
        y += 10
    more = total - shown
    return {
        "width": WIDTH,
        "height": int(y + (36 if more > 0 else 16)),
        "pad": PAD,
        "c": colors,
        "title": data.title,
        "date": f"{data.day:%A} {data.day.day} {data.day:%B}",
        "sections": sections,
        "more": f"and {more} more" if more > 0 else "",
        "more_y": y + 10,
    }


def list_svg(data: ListCardData, theme: str = "light") -> str:
    return write_svg("list_card.svg", **view(data, theme))


def list_text(data: ListCardData) -> str:
    lines = [f"{data.title}, {data.day:%a %d %b}:"]
    for section in data.sections:
        head = f"{section.heading} ({section.note})" if section.note else section.heading
        lines.append(f"{head}:")
        for row in section.rows:
            tick = "" if row.done is None else ("✓ " if row.done else "☐ ")
            lines.append(f"- {tick}{row.text}" + (f" ({row.note})" if row.note else ""))
    return "\n".join(lines)


# ----- tasks ------------------------------------------------------------------------------


def tasks_data(services: Any, member: Member) -> ListCardData | None:
    board = services.get(keys.taskboard)
    summary = services.maybe(keys.day_summary)
    today = summary.today(member) if summary is not None else board._today()
    overdue, now, soon, any_time = [], [], [], []
    for task in board.open_for(member):
        note = "shared" if task.shared else ""
        if task.due_on is None:
            any_time.append((task, Row(task.title, note)))
        elif task.due_on < today:
            when = f"was due {task.due_on:%a %-d %b}"
            overdue.append((task, Row(task.title, when)))
        elif task.due_on == today:
            at = board.time_of(task, today)
            now.append((task, Row(task.title, f"{at:%-I:%M %p}".lower() if at else note)))
        elif task.due_on <= today + timedelta(days=SOON_DAYS):
            soon.append((task, Row(task.title, f"{task.due_on:%a}")))
    parts = [
        ("Overdue", sorted(overdue, key=lambda p: (p[0].due_on, p[0].id))),
        ("Today", now),
        ("Next few days", sorted(soon, key=lambda p: (p[0].due_on, p[0].id))),
        ("Any time", any_time),
    ]
    sections = tuple(Section(name, tuple(r for _, r in rows)) for name, rows in parts if rows)
    if not sections:
        return None
    return ListCardData(f"{member.name}'s tasks", today, sections)


# ----- routines ---------------------------------------------------------------------------


def routines_data(services: Any, member: Member, day: date | None = None) -> ListCardData | None:
    routines = services.get(keys.routines)
    today: date = routines.today(member)
    when: date = day if day is not None else today
    sections = []
    for routine in routines.of(member):
        items = [i for i in routines.items(routine) if i.applies(when)]
        if not items:
            continue
        rows = tuple(Row(i.title, done=(when == today and routines.ticked(i, when))) for i in items)
        sections.append(Section(routine.name, rows, routines.window(routine, member)))
    if not sections:
        return None
    return ListCardData(f"{member.name}'s routines", when, tuple(sections))


async def _send(ctx: ToolContext, data: ListCardData, caption: str, kind: str) -> bool:
    """The card as a picture, or its words. True when a picture went."""
    drawings = ctx.services.maybe(keys.drawings)
    if drawings is not None:
        theme = ctx.services.store.preferences(ctx.member.id, DrawingsPreferences).picture_theme
        png = await drawings.png(list_svg(data, theme), PNG_WIDTH)
        if png is not None and await ctx.services.outbox.send_photo(
            ctx.member, png, caption, kind=kind
        ):
            return True
    await ctx.services.outbox.send(ctx.member, list_text(data), priority=Priority.REPLY, kind=kind)
    return False


@tool(
    "show_tasks_picture",
    "Sends them a picture of their own to-do list: their open tasks, overdue first, then "
    "today's, the next few days' and any time. For 'my tasks as a picture', 'show me my "
    "to-do list as a graphic'. Not the chore chart (show_chore_chart: each person's chores "
    "up now). It's sent as it is: don't list it again.",
    {},
)
async def show_tasks_picture(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.services.maybe(keys.taskboard) is None:
        raise ToolFailed("Tasks aren't set up.")
    data = tasks_data(ctx.services, ctx.member)
    ctx.answered.append("show_tasks_picture")
    if data is None:
        await ctx.services.outbox.send(ctx.member, NO_TASKS_TEXT, priority=Priority.REPLY)
        return "Told them nothing's open. Don't repeat it."
    pictured = await _send(ctx, data, TASKS_CAPTION, "tasks_picture")
    return "Sent their tasks as a picture." if pictured else "Sent their tasks, in words."


@tool(
    "show_routines_picture",
    "Sends them a picture of their morning, afternoon and evening routines for a day, each "
    "item ticked when done. For 'my routines as a picture', 'show tomorrow's routine as a "
    "graphic'. day: 'today', 'tomorrow' or a date (YYYY-MM-DD). It's sent as it is: don't "
    "list it again.",
    {"day": {"type": "string"}},
)
async def show_routines_picture(ctx: ToolContext, args: dict[str, Any]) -> str:
    routines = ctx.services.maybe(keys.routines)
    if routines is None:
        raise ToolFailed("Routines aren't set up.")
    today = routines.today(ctx.member)
    said = str(args.get("day") or "").strip().lower()
    if said in ("", "today"):
        day = today
    elif said == "tomorrow":
        day = today + timedelta(days=1)
    else:
        try:
            day = date.fromisoformat(said)
        except ValueError as exc:
            raise ToolFailed("Which day? 'today', 'tomorrow' or YYYY-MM-DD.") from exc
    data = routines_data(ctx.services, ctx.member, day)
    ctx.answered.append("show_routines_picture")
    if data is None:
        which = "today" if day == today else f"for {day:%A %-d %B}"
        text = NO_ROUTINES_TEXT.format(which=which)
        await ctx.services.outbox.send(ctx.member, text, priority=Priority.REPLY)
        return "Told them there's nothing on them. Don't repeat it."
    pictured = await _send(ctx, data, ROUTINES_CAPTION, "routines_picture")
    return "Sent their routines as a picture." if pictured else "Sent their routines, in words."


@tool(
    "show_day",
    "Sends them a picture of today: the morning picture (the day card), with today's events "
    "at their times, the weather and what's waiting. For 'a picture of my day', 'show me "
    "the morning picture', 'everything as a picture'. It's sent as it is: don't describe it.",
    {},
)
async def show_day(ctx: ToolContext, args: dict[str, Any]) -> str:
    drawings = ctx.services.maybe(keys.drawings)
    if drawings is None:
        raise ToolFailed("Pictures aren't set up.")
    card = drawings.day_card
    png = await card.png(ctx.member, card.today(ctx.member))
    ctx.answered.append("show_day")
    if png is not None and await ctx.services.outbox.send_photo(
        ctx.member, png, DAY_CAPTION, kind="day_picture"
    ):
        return "Sent their day as a picture."
    summary = ctx.services.maybe(keys.day_summary)
    if summary is None:
        raise ToolFailed("The picture couldn't be drawn.")
    today = card.today(ctx.member)
    lines = summary.items(ctx.member, today, partner=True, scope="mine")
    text = (
        f"{today:%a %d %b}:\n" + "\n".join(f"- {line}" for line in lines)
        if lines
        else ("Nothing on the calendar today.")
    )
    await ctx.services.outbox.send(ctx.member, text, priority=Priority.REPLY)
    return "Sent their day, in words."
