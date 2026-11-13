"""The chore chart as a picture (DC9; the Day Card Plan's "Other uses").

A column per person: the chores up on their chart now, as the wall shows them (C2d: up to
their `chart_limit`, plus the important ones that always show), each with a word on when
it's due. Never what waits off the chart: a long list isn't shown by another route. On
request ("show the chore chart"), to whoever asks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themi.accounts import Member
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.drawing.svg import write_svg
from themi.drawing.text import wrap
from themi.standard.day_card import THEMES
from themi.standard.drawings import DrawingsPreferences

if TYPE_CHECKING:
    from themi_home.chore_chart import ChartQueue

TEMPLATES = Path(__file__).parent / "drawing_templates"
WIDTH, HEIGHT = 540, 675
PNG_WIDTH = 1080
PAD = 28
MOST = 7  # cards a column shows; the rest are counted
CAPTION = "The chore chart."
EMPTY_TEXT = "Nothing is up on the chore chart."


@dataclass(frozen=True)
class Chore:
    title: str
    when: str = ""  # "since Tue"
    important: bool = False


@dataclass(frozen=True)
class Column:
    name: str
    chores: tuple[Chore, ...]


@dataclass(frozen=True)
class ChartCardData:
    day: date
    columns: tuple[Column, ...]


def chart_data(queue: ChartQueue, members: list[Member], today: date) -> ChartCardData:
    from themi_home.chore_chart import is_routine

    columns = []
    for member in members:
        up = list(queue.up_for(member))
        seen = {t.id for t in up}
        for task in queue.board.open_for(member):  # the important ones always show (C2d)
            if (
                task.id not in seen
                and task.importance == "high"
                and queue.on_chart(task)
                and not is_routine(task)
                and (task.due_on or today) <= today
            ):
                up.append(task)
        chores = tuple(
            Chore(
                t.title,
                f"since {t.due_on:%a}" if t.due_on and t.due_on < today else "",
                t.importance == "high",
            )
            for t in sorted(up, key=lambda t: (t.due_on or today, t.title))
        )
        columns.append(Column(member.name, chores))
    return ChartCardData(today, tuple(columns))


def chart_text(data: ChartCardData) -> str:
    lines = []
    for column in data.columns:
        if column.chores:
            items = "; ".join(c.title + (f" ({c.when})" if c.when else "") for c in column.chores)
            lines.append(f"- {column.name}: {items}")
    return "On the chore chart:\n" + "\n".join(lines) if lines else EMPTY_TEXT


def view(data: ChartCardData, theme: str = "light") -> dict[str, Any]:
    colors = THEMES[theme]
    count = max(len(data.columns), 1)
    gap = 16.0
    width = (WIDTH - 2 * PAD - gap * (count - 1)) / count
    columns = []
    for i, column in enumerate(data.columns):
        x = PAD + i * (width + gap)
        y = 112.0
        cards = []
        for chore in column.chores[:MOST]:
            lines = wrap(chore.title, 14, width - 28, 2, bold=True)
            height = 22 + 18 * len(lines) + (16 if chore.when else 0)
            cards.append(
                {"y": y, "height": height, "lines": lines, "when": chore.when,
                 "important": chore.important}
            )  # fmt: skip
            y += height + 10
        more = len(column.chores) - MOST
        columns.append(
            {
                "x": x,
                "width": width,
                "name": column.name,
                "cards": cards,
                "more": f"+{more} more" if more > 0 else "",
                "more_y": y + 14,
                "empty": not column.chores,
            }
        )
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "pad": PAD,
        "c": colors,
        "title": "The chore chart",
        "date": f"{data.day:%A} {data.day.day} {data.day:%B}",
        "columns": columns,
    }


def chart_svg(data: ChartCardData, theme: str = "light") -> str:
    return write_svg("chore_card.svg", [TEMPLATES], **view(data, theme))


async def send_chart(ctx_services: Any, member: Member) -> bool:
    """The chart as a picture to `member`, or in words. True when a picture went."""
    queue = ctx_services.maybe(keys.chart_queue)
    if queue is None:
        raise ToolFailed("The chore chart isn't set up.")
    data = chart_data(queue, ctx_services.store.list_members(), queue._today())
    drawings = ctx_services.maybe(keys.drawings)
    if drawings is not None and any(c.chores for c in data.columns):
        theme = ctx_services.store.preferences(member.id, DrawingsPreferences).picture_theme
        png = await drawings.png(chart_svg(data, theme), PNG_WIDTH)
        if png is not None and await ctx_services.outbox.send_photo(
            member, png, CAPTION, kind="chart"
        ):
            return True
    await ctx_services.outbox.send(member, chart_text(data), priority=Priority.REPLY, kind="chart")
    return False


@tool(
    "show_chore_chart",
    "Sends them a picture of the chore chart: what's up for each person now, as the wall "
    "shows it. For 'show me the chore chart', 'what chores are up?'. It's sent as it is: "
    "don't list it again.",
    {},
)
async def show_chore_chart(ctx: ToolContext, args: dict[str, Any]) -> str:
    pictured = await send_chart(ctx.services, ctx.member)
    ctx.answered.append("show_chore_chart")
    return "Sent the chart as a picture." if pictured else "Sent the chart, in words."
