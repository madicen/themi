"""`themi cozyla check`: sign in and show what's there, changing nothing (C1a).

It shows the account's members and to-do lists with how many items are open
and done, whether `COZYLA_TODO_LIST` names one of them, and how a few due
dates come back in local time (Cozyla stores a moment, Themi a date, and this
shows which time of day the wall uses). Titles only with `titles=True`.

`fields=True` (F18d) prints each open to-do on `COZYLA_TODO_LIST` with every field
as Cozyla sends it, in the order it sends them, and every field name seen on any
to-do: to compare with the order the wall shows, and find what (if anything)
places a to-do there.
"""

from __future__ import annotations

import json
from zoneinfo import ZoneInfo

from themi.connectors.cozyla.client import CozylaClient

SAMPLE_DUES = 5


def _same(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


async def check(client: CozylaClient, *, titles: bool = False, fields: bool = False) -> str:
    members = await client.members()
    lists = await client.lists()
    todos = await client.todos()
    wanted = client.config.todo_list
    tz = ZoneInfo(client.timezone)

    lines = [f"Signed in to Cozyla as {client.config.email}. Nothing was changed."]
    lines.append("Members: " + (", ".join(m.name for m in members) or "none"))
    lines.append("To-do lists:")
    for todo_list in lists:
        items = [t for t in todos if t.list_id == todo_list.id]
        done = sum(t.completed for t in items)
        mark = "  <- COZYLA_TODO_LIST" if wanted and _same(todo_list.title, wanted) else ""
        lines.append(f"  {todo_list.title}: {len(items) - done} open, {done} done{mark}")
    if not lists:
        lines.append("  (none)")

    if not wanted:
        lines.append("COZYLA_TODO_LIST isn't set, so nothing syncs. Set it to one of the lists.")
    elif not any(_same(t.title, wanted) for t in lists):
        lines.append(f"COZYLA_TODO_LIST is {wanted!r}, which isn't one of the lists above.")

    dues = sorted({t.due.astimezone(tz) for t in todos if t.due is not None})[-SAMPLE_DUES:]
    if dues:
        shown = ", ".join(d.strftime("%a %d %b %H:%M") for d in dues)
        lines.append(f"Due dates as stored ({client.timezone}): {shown}")
    else:
        lines.append("No to-do has a due date, so how the wall stores them isn't known yet.")

    if titles and wanted:
        chosen = [t for t in lists if _same(t.title, wanted)]
        open_titles = [
            t.title for t in todos if chosen and t.list_id == chosen[0].id and not t.completed
        ]
        lines.append(f"Open on {wanted}: " + ("; ".join(open_titles) or "nothing"))
    if fields and wanted:
        chosen = [t for t in lists if _same(t.title, wanted)]
        names = sorted({key for t in todos for key in t.raw})
        lines.append("Fields on to-dos: " + ", ".join(names))
        lines.append(f"Open on {wanted}, in the order Cozyla sends them, every field:")
        for todo in todos:
            if chosen and todo.list_id == chosen[0].id and not todo.completed:
                lines.append("  " + json.dumps(todo.raw, ensure_ascii=False))
    return "\n".join(lines)
