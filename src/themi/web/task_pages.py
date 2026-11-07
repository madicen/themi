"""Tasks: what's on your list, one row each, with Done on the row and the details on tap.

Only tasks you're doing, or ones you added for someone else, are shown; editing
follows the same rule as in chat (the person doing it, whoever added it, or an
admin), whatever a form says. Done is for the tasks shown here (or any, for an
admin), and goes the same way as Done in chat or on the wall (W2).
"""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import Member, NotFound, PermissionDenied
from themi.core import keys
from themi.core.tasks import Task, TaskBoard
from themi.web.kit import Kit


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
    return {
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
        return kit.with_flash(request, "tasks.html", session, **task_rows(app, session.member))

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
