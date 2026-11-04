"""D5c: scenes, a named run of control panel actions with Themi's clock skipped between them.

Each `Do` is one of the panel's own actions (a section's id, an action's id, its form), so
scenes stay in step with the sections; a test checks every step against them. `At` skips
Themi's clock ahead to the next time of day (on a weekday, if given) and `Wait` skips a
while. After each skip Themi sends whatever came due, as its scheduler would.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any


@dataclass(frozen=True)
class Do:
    section: str
    action: str
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class At:
    clock: str  # "08:00"
    weekday: str = ""  # "Tue": that day, this week or next

    def until(self, now: datetime) -> timedelta:
        """How far ahead the next such moment is (nothing, if it's now)."""
        target = datetime.combine(now.date(), time.fromisoformat(self.clock), now.tzinfo)
        days = 0
        if self.weekday:
            days = (WEEKDAYS.index(self.weekday) - now.weekday()) % 7
        target += timedelta(days=days)
        if target < now:
            target += timedelta(days=7 if self.weekday else 1)
        return target - now


@dataclass(frozen=True)
class Wait:
    minutes: int


Step = Do | At | Wait
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class Scene:
    name: str
    about: str
    steps: tuple[Step, ...]


def describe(step: Step) -> str:
    if isinstance(step, At):
        return f"At {step.weekday + ' ' if step.weekday else ''}{step.clock}"
    if isinstance(step, Wait):
        return f"Wait {step.minutes} minutes"
    shown = ", ".join(f"{v}" for v in step.values.values())
    return f"{step.section} · {step.action}" + (f" ({shown})" if shown else "")


SCENES = (
    Scene(
        "A busy Tuesday",
        "An urgent email at 8, the washer done at 10, the robot trapped at 2.",
        (
            At("08:00", "Tue"),
            Do("email", "preset", {"person": "Erin", "preset": "Urgent: an appointment moved"}),
            At("09:00"),
            Do("laundry", "state", {"machine": "Washer", "state": "Running"}),
            At("10:00"),
            Do("laundry", "state", {"machine": "Washer", "state": "Finished"}),
            Wait(30),
            At("14:00"),
            Do("vacuum", "status", {"status": "Trapped", "room": "Kitchen"}),
        ),
    ),
    Scene(
        "Shopping all over",
        "Groceries added in Keep, OurGroceries and on the wall, and one bought.",
        (
            Do("home", "keep", {"person": "Erin", "text": "oat milk"}),
            Do("groceries", "add", {"item": "Eggs"}),
            Do("wall", "add", {"title": "Pick up the dry cleaning", "person": "Husband"}),
            Wait(60),
            Do("groceries", "cross", {"item": "Eggs"}),
        ),
    ),
    Scene(
        "Everything breaks",
        "Gmail busy, LG's token revoked, Roborock signed out and the wall failing, at once.",
        (
            Do("email", "fault", {"fault": "Gmail is busy (429)", "person": "Erin"}),
            Do("laundry", "fault", {"fault": "LG revokes the token"}),
            Do("vacuum", "fault", {"fault": "The sign-in expires"}),
            Do("wall", "fault", {"fault": "Reading the to-dos fails"}),
            Wait(15),
        ),
    ),
)
