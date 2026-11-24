"""F60e (Michael's idea #263): the body double on the wall.

The frame is shared, so the sheet asks "Who's this?" as Talk to Themi does, and the choice
is the same one (`wall_talk.Talking`). With no session going, it offers a few things to work
on (their tasks due today or before, then their other open ones, and their routines with
something still open today), a mode and a length; Start goes through
`BodyDouble.begin_from_page`, so Telegram gets the start message as from chat. With one
going, the sheet is the session at wall size: the chameleon's scene, the timer, the line and
the same buttons as chat (`BodyDouble.page_buttons`), which act through `act_from_page`, so
the chat message is edited too. The person's column shows a chip while it runs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.core import keys
from themi.localtime import member_day

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from themi.accounts import Member
    from themi.core.services import Services
    from themi_home.body_double import BodyDouble

TASKS_OFFERED = 5
MODES = (
    ("", "Themi picks"),
    ("silent", "Quiet company"),
    ("sprint", "Sprints"),
    ("guided", "Step by step"),
)
LENGTHS = ((0, "Until I'm done"), (25, "25 min"), (50, "50 min"), (90, "1½ hours"))


@dataclass(frozen=True)
class FocusChoice:
    key: str  # "task:12" or "routine:3"
    title: str
    sub: str = ""


def body_double(services: Services) -> BodyDouble | None:
    return services.maybe(keys.body_double)


def choices(services: Services, member: Member, tz: ZoneInfo) -> list[FocusChoice]:
    """What they might work on: tasks due by today first, then other open ones, then their
    routines with something still open today."""
    found: list[FocusChoice] = []
    today = member_day(member, clock.now(), tz)
    board = services.maybe(keys.taskboard)
    if board is not None:
        tasks = [t for t in board.open_for(member) if t.status == "open"]
        due = [t for t in tasks if t.due_on is not None and t.due_on <= today]
        rest = [t for t in tasks if t not in due]
        for task in (due + rest)[:TASKS_OFFERED]:
            sub = (
                "overdue"
                if task.due_on is not None and task.due_on < today
                else "today"
                if task.due_on == today
                else ""
            )
            found.append(FocusChoice(f"task:{task.id}", task.title, sub))
    routines = services.maybe(keys.routines)
    if routines is not None and services.store.db.one(
        "SELECT 1 FROM routines WHERE member_id = ?", (member.id,)
    ):
        day = routines.today(member)
        for routine in routines.of(member):
            left = [i for i in routines.today_items(routine, day) if not routines.ticked(i, day)]
            if left:
                count = f"{len(left)} to do"
                found.append(FocusChoice(f"routine:{routine.id}", f"{routine.name} routine", count))
    return found


def chip(services: Services, member: Member) -> str:
    """ "Body double · 12 min left" (a sprint's block) or "Body double · 20 min in" while a
    session's going for them, else ""."""
    bd = body_double(services)
    if bd is None or bd.current(member) is None:
        return ""
    timer: dict[str, Any] = bd.state(member)["timer"]
    now = clock.now()
    if timer["kind"] == "down":
        left = datetime.fromisoformat(timer["to"]) - now
        return f"Body double · {max(1, math.ceil(left.total_seconds() / 60))} min left"
    gone = now - datetime.fromisoformat(timer["from"])
    return f"Body double · {int(gone.total_seconds() // 60)} min in"


def on_the_wall(state: dict[str, Any], member_id: int) -> dict[str, Any]:
    """The session page's state with its step picture's address turned into the wall's,
    which the frame may load for this person (/session's needs them signed in)."""
    picture = state.get("picture")
    if not picture or not picture.get("url"):
        return state
    url = str(picture["url"]).replace("/session/pictures/", "/wall/focus/picture/", 1)
    url += ("&" if "?" in url else "?") + f"member={member_id}"
    return {**state, "picture": {**picture, "url": url}}
