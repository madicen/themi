"""Pictures of a person's tasks and of their routines (F42g, Michael's bug #206: "should be
able to ask for tasks, routines, maybe everything and get a graphic"), and today's day card
on request. The Day Card Plan's "Other uses" didn't have these; this adds them.

A list card is a title, a date line and sections, each a heading over rows. A row is
words, a short note ("was due Tue", "shared") and, for a routine's items, a tick when done.
Long lists are cut with "and N more", never crammed. No energy, and no count of misses.

- Tasks (`show_tasks_picture`): F43b draws them as cards (`task_card.py`), for one person or
  everyone, with chores if asked.
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
from themi.drawing.emoji import item_emoji
from themi.drawing.svg import write_svg
from themi.drawing.text import fit
from themi.standard.day_card import THEMES
from themi.standard.drawings import DrawingsPreferences
from themi.standard.task_card import cards_svg, cards_text, task_cards

WIDTH = 540
PNG_WIDTH = 1080
PAD = 28
ROW = 30  # px a row takes
HEAD = 34  # px a section's heading takes
MOST = 14  # rows a card shows; the rest are counted
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
    emoji: str = ""  # F43b: one that fits the item's words


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
            inset = (28 if box else 0) + (26 if row.emoji else 0)
            room = WIDTH - 2 * PAD - inset - (120 if row.note else 0)
            rows.append(
                {
                    "y": y,
                    "emoji": row.emoji,
                    "emoji_x": PAD + (28 if box else 0),
                    "text_x": PAD + inset,
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
            emoji = f"{row.emoji} " if row.emoji else ""
            lines.append(f"- {tick}{emoji}{row.text}" + (f" ({row.note})" if row.note else ""))
    return "\n".join(lines)


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
        rows = tuple(
            Row(
                i.title,
                done=(when == today and routines.ticked(i, when)),
                emoji=item_emoji(i.title),
            )
            for i in items
        )
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
    "Sends them a picture of a to-do list as cards, overdue first, then today's, the next "
    "few days' and any time. who: 'me' for their own ('my tasks as a picture'), "
    "'everyone' for the family's ('our tasks', 'the family's tasks': a column each, and "
    "what either can do across the bottom), or a person's name ('Erin's tasks'). "
    "with_chores: true for chores and tasks together ('chores and tasks', 'everything on my "
    "list'): each person's chores up on the chart come first. The chore chart alone is "
    "show_chore_chart. It's sent as it is: don't list it again.",
    {
        "who": {"type": "string", "description": "'me', 'everyone', or a name."},
        "with_chores": {"type": "boolean"},
    },
)
async def show_tasks_picture(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.services.maybe(keys.taskboard) is None:
        raise ToolFailed("Tasks aren't set up.")
    with_chores = bool(args.get("with_chores"))
    note = ""
    if with_chores and ctx.services.maybe(keys.chart_queue) is None:
        with_chores, note = False, " The chore chart isn't set up, so it's tasks only: say so."
    data = task_cards(ctx.services, ctx.member, str(args.get("who") or "me"), with_chores)
    ctx.answered.append("show_tasks_picture")
    if data is None:
        await ctx.services.outbox.send(ctx.member, NO_TASKS_TEXT, priority=Priority.REPLY)
        return "Told them nothing's open. Don't repeat it."
    drawings = ctx.services.maybe(keys.drawings)
    if drawings is not None:
        theme = ctx.services.store.preferences(ctx.member.id, DrawingsPreferences).picture_theme
        png = await drawings.png(cards_svg(data, theme), PNG_WIDTH)
        if png is not None and await ctx.services.outbox.send_photo(
            ctx.member, png, _caption(ctx.member, data), kind="tasks_picture"
        ):
            return "Sent the tasks as a picture." + note
    await ctx.services.outbox.send(
        ctx.member, cards_text(data), priority=Priority.REPLY, kind="tasks_picture"
    )
    return "Sent the tasks, in words." + note


def _caption(member: Member, data: Any) -> str:
    """ "Your tasks." for their own; else the picture's title ("Everyone's tasks.")."""
    if len(data.lanes) == 1 and not data.shared and data.lanes[0].name == member.name:
        return "Your chores and tasks." if "chores" in data.title else TASKS_CAPTION
    return f"{data.title}."


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
