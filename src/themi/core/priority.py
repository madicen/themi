"""Urgent and important (T1, Erin's idea #44): two scales, and the order tasks are offered.

- Urgent: a hard due date that's soon. Overdue, today or tomorrow is urgent; the sooner
  (or the longer overdue), the more urgent.
- Important: there are consequences if it's ignored for good. That's the task's importance
  (F12, C2c): high is important; normal and low aren't, low least of all.

When more than one task nudge is waiting, they go in this order: urgent and important,
urgent only, important only, then neither. An important-only task left waiting a week
moves ahead of the urgent-only ones, so the urgent never crowd it out for good.

Only ever in words ("urgent and important"); never numbers or scores.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from themi.core.tasks import Task

URGENT_WITHIN = 1  # days until due: today or tomorrow (or overdue)
NEGLECTED_AFTER = timedelta(days=7)  # an important-only task waiting this long goes first
IMPORTANCE_ORDER = {"high": 0, "normal": 1, "low": 2}


def is_urgent(task: Task, today: date) -> bool:
    return task.due_on is not None and (task.due_on - today).days <= URGENT_WITHIN


def is_important(task: Task) -> bool:
    return task.importance == "high"


def words(task: Task, today: date) -> str:
    """ "urgent and important", "urgent", "important", or "" for neither."""
    urgent, important = is_urgent(task, today), is_important(task)
    if urgent and important:
        return "urgent and important"
    return "urgent" if urgent else "important" if important else ""


def rank(task: Task, today: date, waiting_since: datetime, now: datetime) -> tuple[int, ...]:
    """Lower goes first: the quadrant, then the nearer due date, then the importance."""
    urgent, important = is_urgent(task, today), is_important(task)
    if urgent and important:
        quadrant = 0
    elif important and now - waiting_since >= NEGLECTED_AFTER:
        quadrant = 1  # left too long: ahead of the urgent-only
    elif urgent:
        quadrant = 2
    elif important:
        quadrant = 3
    else:
        quadrant = 4
    days = (task.due_on - today).days if task.due_on else 10_000
    return (quadrant, days, IMPORTANCE_ORDER.get(task.importance, 1))
