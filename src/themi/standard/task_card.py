"""The tasks picture as cards (F43b, Michael's idea #208: "the tasks picture should be more
graphical like the chore chart. The user should be able to get both combined and if there
are emoji assigned, they should be included in the picture").

Cards in the chore chart's style, each with its emoji (a mirror's icon, else one picked
from the title; `themi.drawing.emoji.item_emoji`), its title and a note under it. A
person's cards keep the morning list's order: overdue, today, the next few days, any time,
each group under a small heading. Urgent-and-important ones get the chart's important edge.

- One person ("my tasks", "Erin's tasks"): one lane, the full width, two cards across.
- Everyone ("our tasks", "the family's tasks"): a lane per person, and the tasks either of
  them can do in an "Either of you" row across the bottom (Michael, 2026-11-14).
- With chores ("chores and tasks"): each lane starts with that person's chores up on the
  chart now ("On the chart"); a task that's on the chart is drawn once, as a chore.

Long lanes are cut with "+N more", never crammed. No energy, and no count of misses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from themi.accounts import Member
from themi.core import keys
from themi.core.tools import ToolFailed
from themi.drawing.emoji import item_emoji
from themi.drawing.svg import write_svg
from themi.drawing.text import wrap
from themi.standard.day_card import THEMES

WIDTH = 540
PNG_WIDTH = 1080
PAD = 28
GAP = 16  # between lanes
ACROSS_GAP = 12  # between cards side by side
TOP = 100.0  # where the first lane's name (or first heading) goes
MOST = 7  # cards a lane shows (twice that with two across); the rest are counted
MOST_SHARED = 4  # cards the "Either of you" row shows
SOON_DAYS = 3  # "the next few days"
CHART_HEADING = "On the chart"
SHARED_NAME = "Either of you"
EVERYONE = ("everyone", "everybody", "us", "our", "all", "both")
# F65d (bug #281): "the family chores", "the Either of you list": the shared list alone, all
# of it.
FAMILY = (
    "family", "the family", "family's", "the family's", "shared", "together", "either of you",
    "either", "the family list", "family list", "the shared list", "shared list",
)  # fmt: skip
FAMILY_TITLE = "The family's {what}"
FAMILY_TODO = "Family to-do"


@dataclass(frozen=True)
class Card:
    title: str
    note: str = ""  # "was due Fri 6 Nov", "2:30 pm", "Wed", "since Tue"
    emoji: str = ""
    important: bool = False


@dataclass(frozen=True)
class Group:
    heading: str
    cards: tuple[Card, ...]


@dataclass(frozen=True)
class Lane:
    name: str
    groups: tuple[Group, ...]

    @property
    def count(self) -> int:
        return sum(len(g.cards) for g in self.groups)


@dataclass(frozen=True)
class TaskCardData:
    title: str
    day: date
    lanes: tuple[Lane, ...]
    shared: tuple[Card, ...] = ()
    everything: bool = False  # F65d: every card drawn, none counted into "+N more"


# ----- the data ---------------------------------------------------------------------------


def whose(services: Any, member: Member, who: str) -> list[Member] | None:
    """The people a picture is of: [them], [a named person], or None for everyone."""
    said = who.strip().casefold()
    if said in ("", "me", "mine", "my", member.name.casefold()):
        return [member]
    if said in EVERYONE:
        return None
    members = services.store.list_members()
    named = [m for m in members if m.name.casefold() == said.removesuffix("'s")]
    if not named:
        names = ", ".join(m.name for m in members)
        raise ToolFailed(f"There's nobody called {who} here ({names}). Ask whose they mean.")
    return named


def task_cards(
    services: Any, member: Member, who: str = "me", with_chores: bool = False
) -> TaskCardData | None:
    """The cards for `who`'s tasks (and chores), or None when there's nothing to draw."""
    board = services.get(keys.taskboard)
    summary = services.maybe(keys.day_summary)
    today: date = summary.today(member) if summary is not None else board._today()
    if who.strip().casefold() in FAMILY:
        return family_cards(services, board, today, with_chores)
    chosen = whose(services, member, who)
    people = chosen if chosen is not None else services.store.list_members()
    queue = services.maybe(keys.chart_queue) if with_chores else None
    shared: dict[int, Any] = {}
    lanes = []
    for person in people:
        groups = []
        drawn: set[int] = set()
        if queue is not None:
            chores = queue.chart_for(person, today)
            drawn = {t.id for t in chores}
            cards = tuple(_chore_card(board, t, today) for t in chores)
            if cards:
                groups.append(Group(CHART_HEADING, cards))
        tasks = []
        for task in board.open_for(person):
            if task.id in drawn:
                continue  # on the chart: drawn once, as a chore
            if chosen is None and (task.shared or task.either):
                shared.setdefault(task.id, task)
                continue
            tasks.append(task)
        groups.extend(_grouped(board, tasks, today, note_shared=chosen is not None))
        lanes.append(Lane(person.name, tuple(groups)))
    if chosen is None:
        lanes = [lane for lane in lanes if lane.groups] or lanes
    shared_cards = tuple(
        _task_card(board, t, today) for t in sorted(shared.values(), key=_order(today))
    )
    if not any(lane.groups for lane in lanes) and not shared_cards:
        return None
    what = "chores and tasks" if queue is not None else "tasks"
    title = f"{people[0].name}'s {what}" if chosen is not None else f"Everyone's {what}"
    return TaskCardData(title, today, tuple(lanes), shared_cards)


def family_cards(services: Any, board: Any, today: date, with_chores: bool) -> TaskCardData | None:
    """F65d: the shared list alone, every item: "Either of you" then "Family to-do", each
    in the tasks' order (overdue first), each card saying when it was due."""
    found: dict[int, Any] = {}
    for person in services.store.list_members():
        for task in board.open_for(person):
            if task.shared or task.either:
                found.setdefault(task.id, task)
    ordered = sorted(found.values(), key=_order(today))
    either = tuple(_task_card(board, t, today) for t in ordered if t.either)
    family = tuple(_task_card(board, t, today) for t in ordered if not t.either)
    groups = tuple(
        Group(name, cards) for name, cards in ((SHARED_NAME, either), (FAMILY_TODO, family)) if cards
    )
    if not groups:
        return None
    what = "chores and tasks" if with_chores else "tasks"
    return TaskCardData(
        FAMILY_TITLE.format(what=what), today, (Lane("Family", groups),), everything=True
    )


def _order(today: date) -> Any:
    return lambda t: (t.due_on is None, t.due_on or today, t.id)


def _grouped(board: Any, tasks: list[Any], today: date, *, note_shared: bool) -> list[Group]:
    overdue, now, soon, any_time = [], [], [], []
    for task in sorted(tasks, key=_order(today)):
        card = _task_card(board, task, today, note_shared=note_shared)
        if task.due_on is None:
            any_time.append(card)
        elif task.due_on < today:
            overdue.append(card)
        elif task.due_on == today:
            now.append(card)
        elif task.due_on <= today + timedelta(days=SOON_DAYS):
            soon.append(card)
    parts = (("Overdue", overdue), ("Today", now), ("Next few days", soon), ("Any time", any_time))
    return [Group(name, tuple(cards)) for name, cards in parts if cards]


def _task_card(board: Any, task: Any, today: date, *, note_shared: bool = False) -> Card:
    if task.due_on is None:
        note = ""
    elif task.due_on < today:
        note = f"was due {task.due_on:%a %-d %b}"
    elif task.due_on == today:
        at = board.time_of(task, today)
        note = f"{at:%-I:%M %p}".lower() if at else ""
    else:
        note = f"{task.due_on:%a}"
    if note_shared and (task.shared or task.either):
        note = f"{note}, shared" if note else "shared"
    urgent = task.due_on is not None and task.due_on <= today
    return Card(
        task.title,
        note,
        item_emoji(task.title, board.icon_of(task)),
        urgent and task.importance == "high",
    )


def _chore_card(board: Any, task: Any, today: date) -> Card:
    since = f"since {task.due_on:%a}" if task.due_on and task.due_on < today else ""
    return Card(
        task.title,
        since,
        item_emoji(task.title, board.icon_of(task)),
        task.importance == "high",
    )


# ----- words, when there's no picture -----------------------------------------------------


def cards_text(data: TaskCardData) -> str:
    lines = [f"{data.title}, {data.day:%a %d %b}:"]
    several = len(data.lanes) > 1 or bool(data.shared)
    for lane in data.lanes:
        if several:
            lines.append(f"{lane.name}:" if lane.groups else f"{lane.name}: nothing open")
        for group in lane.groups:
            lines.append(f"{group.heading}:")
            lines.extend(f"- {_words(card)}" for card in group.cards)
    if data.shared:
        lines.append(f"{SHARED_NAME}:")
        lines.extend(f"- {_words(card)}" for card in data.shared)
    return "\n".join(lines)


def _words(card: Card) -> str:
    emoji = f"{card.emoji} " if card.emoji else ""
    return f"{emoji}{card.title}" + (f" ({card.note})" if card.note else "")


# ----- the picture ------------------------------------------------------------------------


def _card_view(card: Card, x: float, y: float, width: float) -> dict[str, Any]:
    text_x = x + (38 if card.emoji else 14)
    lines = wrap(card.title, 14, x + width - 12 - text_x, 2, bold=True)
    height = 22 + 18 * len(lines) + (16 if card.note else 0)
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text_x": text_x,
        "lines": lines,
        "note": card.note,
        "emoji": card.emoji,
        "important": card.important,
    }


def _lay(cards: list[Card], x: float, y: float, width: float, across: int) -> tuple[list, float]:
    """Cards in rows of `across`; the views and the y under the last row."""
    each = (width - ACROSS_GAP * (across - 1)) / across
    views = []
    for start in range(0, len(cards), across):
        row = [
            _card_view(card, x + i * (each + ACROSS_GAP), y, each)
            for i, card in enumerate(cards[start : start + across])
        ]
        tallest = max(v["height"] for v in row)
        for v in row:
            v["height"] = tallest
        views.extend(row)
        y += tallest + 10
    return views, y


def view(data: TaskCardData, theme: str = "light") -> dict[str, Any]:
    colors = THEMES[theme]
    count = max(len(data.lanes), 1)
    across = 2 if count == 1 else 1
    most = MOST * across if not data.everything else 10_000
    width = (WIDTH - 2 * PAD - GAP * (count - 1)) / count
    named = count > 1 or bool(data.shared)
    lanes, bottom = [], TOP
    for i, lane in enumerate(data.lanes):
        x = PAD + i * (width + GAP)
        y = TOP + (12 if named else -8)
        headings, cards, shown = [], [], 0
        for group in lane.groups:
            if shown >= most:
                break
            take = list(group.cards[: most - shown])
            headings.append({"y": y + 12, "text": group.heading})
            laid, y = _lay(take, x, y + 20, width, across)
            cards.extend(laid)
            shown += len(take)
        more = lane.count - shown
        lanes.append(
            {
                "x": x,
                "name": lane.name if named else "",
                "headings": headings,
                "cards": cards,
                "more": f"+{more} more" if more > 0 else "",
                "more_y": y + 8,
                "empty": not lane.groups,
            }
        )
        bottom = max(bottom, y + (22 if more > 0 else 0), TOP + 50)
    shared: dict[str, Any] | None = None
    if data.shared:
        y = bottom + 18
        laid, end = _lay(list(data.shared[:MOST_SHARED]), PAD, y + 12, WIDTH - 2 * PAD, 2)
        more = len(data.shared) - MOST_SHARED
        shared = {
            "y": y,
            "name": SHARED_NAME,
            "cards": laid,
            "more": f"+{more} more" if more > 0 else "",
            "more_y": end + 8,
        }
        bottom = end + (22 if more > 0 else 0)
    return {
        "width": WIDTH,
        "height": int(bottom + 18),
        "pad": PAD,
        "c": colors,
        "title": data.title,
        "date": f"{data.day:%A} {data.day.day} {data.day:%B}",
        "lanes": lanes,
        "shared": shared,
        "cards": [c for lane in lanes for c in lane["cards"]] + (shared["cards"] if shared else []),
    }


def cards_svg(data: TaskCardData, theme: str = "light") -> str:
    return write_svg("task_card.svg", **view(data, theme))
