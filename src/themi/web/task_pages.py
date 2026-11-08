"""Tasks: what's on your list, one row each, with Done on the row and the details on tap.

Only tasks you're doing, or ones you added for someone else, are shown; editing
follows the same rule as in chat (the person doing it, whoever added it, or an
admin), whatever a form says. Done is for the tasks shown here (or any, for an
admin), and goes the same way as Done in chat or on the wall (W2).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import Member, NotFound, PermissionDenied
from themi.core import keys
from themi.standard import priority
from themi.standard.praise import TasksPreferences
from themi.standard.tasks import Task, TaskBoard
from themi.web.kit import Kit

HOME_TASKS = 5  # W2: the dashboard shows the first few, with Done

# F32a: the ways the Tasks page can group them, with the words on its chips.
GROUPINGS = {
    "due": "Due date",
    "urgency": "Urgency",
    "kind": "Kind",
    "repeats": "Repeats",
    "none": "None",
}
KIND_HEADINGS = {
    "call": "Calls",
    "errand": "Errands",
    "physical": "Around the house",
    "text": "Messages and online",
}


def grouping_of(value: str | None) -> str:
    """A grouping the page knows; anything else is by due date."""
    return value if value in GROUPINGS else "due"


def _due_heading(task: Task, today: date) -> str:
    if task.due_on is None:
        return "No due date"
    if task.due_on < today:
        return "Overdue"
    if task.due_on == today:
        return "Today"
    if task.due_on == today + timedelta(days=1):
        return "Tomorrow"
    sunday = today + timedelta(days=6 - today.weekday())
    if task.due_on <= sunday:
        return "This week"
    if task.due_on <= sunday + timedelta(days=7):
        return "Next week"
    return "Later"


def _urgency_heading(task: Task, today: date) -> str:
    urgent, important = priority.is_urgent(task, today), priority.is_important(task)
    if urgent and important:
        return "Urgent and important"
    return "Urgent" if urgent else "Important" if important else "Neither"


def _repeats_heading(task: Task, today: date) -> str:
    if task.check_in:
        return "Check-ins"
    return "Repeating chores" if task.repeats else "One-offs"


HEADINGS: dict[str, tuple[tuple[str, ...], Callable[[Task, date], str]]] = {
    "due": (
        ("Overdue", "Today", "Tomorrow", "This week", "Next week", "Later", "No due date"),
        _due_heading,
    ),
    "urgency": (("Urgent and important", "Urgent", "Important", "Neither"), _urgency_heading),
    "kind": (
        tuple(KIND_HEADINGS.values()),
        lambda task, today: KIND_HEADINGS.get(task.kind, "Around the house"),
    ),
    "repeats": (("One-offs", "Repeating chores", "Check-ins"), _repeats_heading),
}


def group_tasks(tasks: list[Task], by: str, today: date) -> list[tuple[str, list[Task]]]:
    """The tasks under headings, in order, with empty groups left out. Within a group they
    keep the page's order (overdue first, then by due date, undated last). `none`: one
    group with no heading. Words only, never a score."""
    ordered = sorted(tasks, key=lambda t: _order(t, today))
    by = grouping_of(by)
    if by == "none":
        return [("", ordered)] if ordered else []
    headings, heading_of = HEADINGS[by]
    groups: dict[str, list[Task]] = {h: [] for h in headings}
    for task in ordered:
        groups[heading_of(task, today)].append(task)
    return [(h, found) for h, found in groups.items() if found]


def home_panel(services: Any) -> Callable[[Member], dict[str, Any]]:
    """CR17a: the dashboard's "On your list" panel: the first few, and how many there are."""
    app = SimpleNamespace(services=services, store=services.store)

    def values(member: Member) -> dict[str, Any]:
        rows = task_rows(app, member, limit=HOME_TASKS)
        total = len(services.get(keys.taskboard).open_for(member))
        return {**rows, "more_tasks": total if total > HOME_TASKS else 0}

    return values


def task_rows(app: Any, member: Member, limit: int | None = None) -> dict[str, Any]:
    """What `_task_row.html` needs: the member's tasks, overdue first, then by due date
    (undated last), and those they added for someone else. Home shows the first `limit`."""
    board: TaskBoard = app.services.maybe(keys.taskboard)
    family = app.store.get_family()
    tz = ZoneInfo(family.timezone if family else "UTC")
    today = board._today()
    mine = sorted(board.open_for(member), key=lambda t: _order(t, today))
    if limit is not None:
        mine = mine[:limit]
    added = [
        t
        for t in board.added_by(member)
        if t.assignee != member.id and t.id not in {m.id for m in mine}
    ]
    if limit is not None:
        added = []
    shown = [*mine, *added]
    parts = app.services.maybe(keys.task_parts)  # F26c: where a part stands
    return {
        "parts": {
            t.id: note.removesuffix(".")
            for t in shown
            if parts is not None and (note := parts.note(t))
        },
        "mine": mine,
        "added": added,
        "names": {m.id: m.name for m in app.store.list_members()},
        "runs": {
            t.id: [r for r in board.runs(t.id) if not r.missed][-5:] for t in shown if t.repeats
        },
        "upcoming": {t.id: board.next_dates(t) for t in shown if t.repeat},
        "summary": board.summary,
        "today": today,
        "tz": tz,
    }


def _order(task: Task, today: date) -> tuple[int, date, int]:
    if task.due_on is None:
        return (2, date.max, task.id)
    return (0 if task.due_on < today else 1, task.due_on, task.id)


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def board() -> TaskBoard:
        assert app.services.maybe(keys.taskboard) is not None
        return app.services.maybe(keys.taskboard)

    @router.get("/tasks", response_class=HTMLResponse)
    def tasks_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        rows = task_rows(app, session.member)
        asked = request.query_params.get("group")  # a shared link: shown once, not saved
        saved = app.store.preferences(session.member.id, TasksPreferences).task_grouping
        by = grouping_of(asked if asked is not None else saved)
        return kit.with_flash(
            request,
            "tasks.html",
            session,
            **rows,
            grouping=by,
            groupings=GROUPINGS,
            groups=group_tasks(rows["mine"], by, rows["today"]),
        )

    @router.post("/tasks/grouping")
    async def save_grouping(request: Request) -> Response:
        session, form = await kit.checked(request)
        by = grouping_of(str(form.get("group", "")))
        app.store.save_preferences(
            session.member, session.member.id, TasksPreferences, task_grouping=by
        )
        return kit.redirect("/tasks")

    @router.post("/tasks/{task_id}/done")
    async def done(request: Request, task_id: int) -> Response:
        session, form = await kit.checked(request)
        member = session.member
        back = "/" if form.get("back") == "home" else "/tasks"
        try:
            task = board().get(task_id)
        except NotFound:
            task = None
        shown = {t.id for t in [*board().open_for(member), *board().added_by(member)]}
        if task is None or not (member.is_admin or task.id in shown):
            said = "That task isn't one you can mark done here."
        else:
            said = await board().complete(task.id, member, interactive=True)
        if request.headers.get("HX-Request"):
            return kit.page(request, "_task_done.html", title=task.title if task else "", said=said)
        return kit.redirect(back, said)

    @router.post("/tasks/{task_id}/edit")
    async def edit_task(request: Request, task_id: int) -> Response:
        session, form = await kit.checked(request)
        steps = str(form.get("steps", "")).splitlines()
        try:
            await board().update(
                task_id, session.member, title=str(form.get("title", "")), steps=steps
            )
        except (NotFound, PermissionDenied):
            return kit.redirect("/tasks", "That task isn't one you can change.")
        except ValueError as exc:
            return kit.redirect("/tasks", str(exc))
        return kit.redirect("/tasks", "Saved.")

    return router
