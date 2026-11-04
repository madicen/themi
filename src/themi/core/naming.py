"""P8a: how often a naming check says no, and how often it's wrong.

A task tool (complete_task, cancel_task, reschedule_task, add_follow_up) is refused when
nothing they said names the task (`not_named`, bug #119: "I ran this morning" for "Go for
a run"), or when it names another open task instead (`names_other`, "We contacted Erin's
parents" for the bins). Each refusal is kept here by kind, without the message.

What follows says whether it was right. The same tool going through for the same person
within `SETTLE_WITHIN` on the same task: the refusal was wrong (they meant it, and said so
again). On another task: it was right. Nothing: no outcome. `themi feedback` prints the
counts per week; they decide whether P8b's embedding fallback gets built.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.localtime import to_utc_iso
from themi.storage.db import Database

log = logging.getLogger(__name__)

# The tools with a naming check: one going through settles a refusal of the same tool.
CHECKED = frozenset({"complete_task", "cancel_task", "reschedule_task", "add_follow_up"})
NOT_NAMED = "not_named"
NAMES_OTHER = "names_other"
SETTLE_WITHIN = timedelta(minutes=10)
KEPT = timedelta(weeks=12)
WEEKS_SHOWN = 8


def task_of(arguments: Mapping[str, Any]) -> int | None:
    """The task a tool call is about: its task, or the one a follow-up comes after."""
    task_id = arguments.get("task_id", arguments.get("after_task_id"))
    return task_id if isinstance(task_id, int) and task_id > 0 else None


class NamingRefusals:
    def __init__(self, db: Database) -> None:
        self.db = db

    def refused(self, member_id: int, tool: str, kind: str, task_id: int | None) -> None:
        now = clock.now()
        try:
            self.db.execute(
                "INSERT INTO naming_refusals (member_id, tool, kind, task_id, refused_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (member_id, tool, kind, task_id, to_utc_iso(now)),
            )
            self.db.execute(
                "DELETE FROM naming_refusals WHERE refused_at < ?", (to_utc_iso(now - KEPT),)
            )
        except sqlite3.Error:  # never lose an answer over a count
            log.warning("Couldn't record a naming refusal", exc_info=True)

    def went_through(self, member_id: int, tool: str, task_id: int) -> None:
        """The tool did its work: settles this person's open refusals of it from the last
        ten minutes."""
        now = clock.now()
        try:
            self.db.execute(
                "UPDATE naming_refusals SET settled_at = ?, "
                "outcome = CASE WHEN task_id = ? THEN 'wrong' ELSE 'right' END "
                "WHERE member_id = ? AND tool = ? AND outcome IS NULL AND refused_at >= ?",
                (to_utc_iso(now), task_id, member_id, tool, to_utc_iso(now - SETTLE_WITHIN)),
            )
        except sqlite3.Error:
            log.warning("Couldn't settle a naming refusal", exc_info=True)

    def weeks(self, count: int = WEEKS_SHOWN) -> list[Week]:
        """The last `count` weeks (seven days each, back from now), newest first."""
        now = clock.now()
        weeks = []
        for n in range(count):
            end, start = now - timedelta(weeks=n), now - timedelta(weeks=n + 1)
            rows = self.db.query(
                "SELECT kind, outcome FROM naming_refusals WHERE refused_at > ? "
                "AND refused_at <= ?",
                (to_utc_iso(start), to_utc_iso(end)),
            )
            weeks.append(
                Week(
                    ending=end,
                    not_named=sum(r["kind"] == NOT_NAMED for r in rows),
                    names_other=sum(r["kind"] == NAMES_OTHER for r in rows),
                    wrong=sum(r["outcome"] == "wrong" for r in rows),
                    right=sum(r["outcome"] == "right" for r in rows),
                )
            )
        return weeks


@dataclass(frozen=True)
class Week:
    ending: datetime
    not_named: int
    names_other: int
    wrong: int  # the same task went through within ten minutes
    right: int  # another task did

    @property
    def refused(self) -> int:
        return self.not_named + self.names_other


def report(weeks: list[Week], timezone: str) -> str:
    """The weeks with a refusal, for `themi feedback`."""
    shown = [w for w in weeks if w.refused]
    if not shown:
        return ""
    lines = [
        '# "Which task?" refusals (P8a)',
        "",
        "Task tools refused because what they said didn't name the task, or named another. "
        "Wrong: the same task went through within ten minutes. Right: another task did.",
        "",
    ]
    for week in shown:
        ending = week.ending.astimezone(ZoneInfo(timezone)).strftime("%a %d %b")
        rest = week.refused - week.wrong - week.right
        lines.append(
            f"- Week to {ending}: {week.refused} refused ({week.not_named} not named, "
            f"{week.names_other} named another); {week.wrong} wrong, {week.right} right, "
            f"{rest} with nothing after."
        )
    return "\n".join(lines) + "\n"
