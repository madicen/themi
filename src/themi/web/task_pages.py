"""Tasks: what's on your list, with each chore's steps, editable.

Only tasks you're doing, or ones you added for someone else, are shown; editing
follows the same rule as in chat (the person doing it, whoever added it, or an
admin), whatever a form says.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import NotFound, PermissionDenied
from themi.core.tasks import TaskBoard
from themi.web.kit import Kit


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def board() -> TaskBoard:
        assert app.services.taskboard is not None
        return app.services.taskboard

    @router.get("/tasks", response_class=HTMLResponse)
    def tasks_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        member = session.member
        mine = board().open_for(member)
        added = [
            t
            for t in board().added_by(member)
            if t.assignee != member.id and t.id not in {m.id for m in mine}
        ]
        names = {m.id: m.name for m in app.store.list_members()}
        return kit.with_flash(request, "tasks.html", session, mine=mine, added=added, names=names)

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
