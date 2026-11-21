"""An email notice's buttons (F50c, Michael's idea #233: "urgent email notices aren't
actionable"): [Open in Gmail], [Not important], [Mark read], [Make it a task].

The urgent and time-sensitive alerts (triage) and the unusual-amount alert (expected
emails) carry them. A tap does it and redraws the notice: the line saying what happened
under it, that button gone, and an [Undo] for "not important" and the task. [Open in Gmail]
is a link (no callback) and always stays.

What a redraw needs (the notice's words, what's been done) rides in the buttons' payloads,
which stay on the server, so a tap needs nothing else.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from themi.accounts import LinkedAccount
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import keys
from themi_google.connectors.gmail.parse import web_link

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi.core.services import Services

OPEN_LABEL = "Open in Gmail"
QUIET_LABEL = "Not important"
READ_LABEL = "Mark read"
TASK_LABEL = "Make it a task"
UNDO_LABEL = "Undo"
NOTICE_KIND = "email"  # the outbox kind of triage's alerts
NOTICE_KEY = "email-urgent:"  # their dedupe key, before the email's id

QUIET_TEXT = "Mail from {label} won't alert you again."
QUIET_UNDONE_TEXT = "Mail from {label} alerts you as before."
READ_TEXT = "Marked read."
TASK_TEXT = "Task added: {title}."
TASK_UNDONE_TEXT = "Taken off your tasks: {title}."
NOT_YOURS_TEXT = "That's {name}'s inbox, so it's theirs to sort."
GONE_TEXT = "That email isn't here any more."

TITLE_MAX = 70
_CLAUSE = re.compile(r"[,;:.!?](?:\s|$)")


def task_title(row: dict[str, Any]) -> str:
    """A task's title from an email: its summary's first clause ("Crunchyroll account
    accessed from a new device in Mountain View"), or its subject."""
    said = " ".join(str(row.get("summary") or row.get("subject") or "the email").split())
    title = _CLAUSE.split(said, maxsplit=1)[0].strip() or said
    if len(title) > TITLE_MAX:
        title = title[:TITLE_MAX].rsplit(" ", 1)[0]
    return title[:1].upper() + title[1:]


def notice_buttons(
    services: Services,
    row: dict[str, Any],
    notice: str,
    *,
    keep: list[Button] | None = None,
    state: dict[str, Any] | None = None,
) -> list[Button]:
    """The notice's buttons as things stand. `keep`: the notice's own buttons, after
    these ("Resume automatic"). `state`: what's been done (from a tap's payload)."""
    account = services.store.get_linked_account(row["account_id"])
    state = state or {
        "email": row["id"],
        "notice": notice,
        "lines": [],
        "used": [],
        "keep": [_dump(b) for b in keep or []],
    }
    used = set(state["used"])
    out = [Button(OPEN_LABEL, "email_open", url=web_link(account.address, row["gmail_id"]))]
    if "quiet" not in used and services.maybe(keys.email_audit) is not None:
        out.append(Button(QUIET_LABEL, "email_quiet", state))
    if "read" not in used:
        out.append(Button(READ_LABEL, "email_read", state))
    if "task" not in used and services.maybe(keys.taskboard) is not None:
        out.append(Button(TASK_LABEL, "email_task", state))
    if state.get("undo"):
        out.append(Button(UNDO_LABEL, "email_undo", state))
    out.extend(_load(b) for b in state.get("keep", []))
    return out


def _dump(button: Button) -> dict[str, Any]:
    return {"label": button.label, "kind": button.kind, "payload": button.payload}


def _load(data: dict[str, Any]) -> Button:
    return Button(data["label"], data["kind"], data.get("payload") or {})


class EmailNoticeButtons:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def install(self) -> None:
        handlers = self.services.button_handlers
        handlers["email_quiet"] = self.on_quiet
        handlers["email_read"] = self.on_read
        handlers["email_task"] = self.on_task
        handlers["email_undo"] = self.on_undo
        self.services.outbox.refreshers[NOTICE_KIND] = self._with_buttons

    def _with_buttons(self, member: Member, row: dict[str, Any]) -> str | tuple[str, list[Button]]:
        """F55b (bug #240): a notice queued before F50c (or held since) gets its buttons when
        it goes, as a new one would. One with buttons, or whose email is gone, is as it was."""
        text = str(row["text"])
        key = str(row.get("dedupe_key") or "")
        if row["buttons"] not in ("[]", "") or not key.startswith(NOTICE_KEY):
            return text
        try:
            email_id = int(key.removeprefix(NOTICE_KEY))
        except ValueError:
            return text
        email = self.db.one("SELECT * FROM emails WHERE id = ?", (email_id,))
        if email is None:  # an account unlinked takes its emails with it
            return text
        return text, notice_buttons(self.services, email, text)

    # ----- the taps ------------------------------------------------------------------

    async def on_quiet(self, event: InboundEvent) -> None:
        found = await self._open(event)
        audit = self.services.maybe(keys.email_audit)
        if found is None or audit is None:
            return
        state, row, account = found
        label = row["from_name"] or row["from_address"]
        snapshot = audit.levels_snapshot(account, row["from_address"])
        _, importance = audit.sender_levels(account.id, row["from_address"])
        await audit.set_levels(account, row["from_address"], label, 0, importance)
        await self._redraw(
            event, row, state, QUIET_TEXT.format(label=label), use="quiet",
            undo={"what": "quiet", "snapshot": snapshot},
        )  # fmt: skip

    async def on_read(self, event: InboundEvent) -> None:
        found = await self._open(event)
        if found is None:
            return
        state, row, _ = found
        sender = (
            f"{row['from_name']} <{row['from_address']}>"
            if row["from_name"]
            else row["from_address"]
        )
        outcome = await self.services.autonomy.stage(
            "email_mark_read",
            event.member,
            f"Mark as read: {row['subject'] or '(no subject)'} (from {sender})",
            {"email_id": row["id"]},
            "gmail.mark_read",
            interactive=True,
            requested=True,  # they tapped for exactly this
        )
        line = READ_TEXT if outcome.action.status == "done" else ""  # else its approval card
        await self._redraw(event, row, state, line, use="read")

    async def on_task(self, event: InboundEvent) -> None:
        found = await self._open(event)
        board = self.services.maybe(keys.taskboard)
        if found is None or board is None:
            return
        state, row, _ = found
        title = task_title(row)
        task = await board.create(
            event.member, title, "text", 1, assignee=event.member, nudge=False, interactive=True
        )
        await self._redraw(
            event, row, state, TASK_TEXT.format(title=title), use="task",
            undo={"what": "task", "task": task.id, "title": title},
        )  # fmt: skip

    async def on_undo(self, event: InboundEvent) -> None:
        found = await self._open(event)
        if found is None:
            return
        state, row, account = found
        undo = state.get("undo") or {}
        if undo.get("what") == "quiet":
            audit = self.services.maybe(keys.email_audit)
            if audit is not None:
                await audit.restore_levels(account, row["from_address"], undo["snapshot"])
            label = row["from_name"] or row["from_address"]
            line, gives_back = QUIET_UNDONE_TEXT.format(label=label), "quiet"
        elif undo.get("what") == "task":
            board = self.services.maybe(keys.taskboard)
            if board is not None:
                await board.cancel(int(undo["task"]), event.member, interactive=True)
            line, gives_back = TASK_UNDONE_TEXT.format(title=undo["title"]), "task"
        else:
            return
        state = {**state, "used": [u for u in state["used"] if u != gives_back]}
        await self._redraw(event, row, state, line)

    # ----- shared ----------------------------------------------------------------------

    async def _open(
        self, event: InboundEvent
    ) -> tuple[dict[str, Any], dict[str, Any], LinkedAccount] | None:
        """The tap's state, its email and the inbox, when the one who tapped owns it."""
        assert event.button is not None
        state = dict(event.button.payload)
        row = self.db.one("SELECT * FROM emails WHERE id = ?", (int(state.get("email", 0)),))
        if row is None:
            await self._say(event, GONE_TEXT)
            return None
        account = self.services.store.get_linked_account(row["account_id"])
        if account.member_id != event.member.id:
            owner = self.services.store.get_member(account.member_id)
            await self._say(event, NOT_YOURS_TEXT.format(name=owner.name))
            return None
        return state, row, account

    async def _redraw(
        self,
        event: InboundEvent,
        row: dict[str, Any],
        state: dict[str, Any],
        line: str,
        *,
        use: str | None = None,
        undo: dict[str, Any] | None = None,
    ) -> None:
        lines = [*state["lines"], line] if line else list(state["lines"])
        used = [*state["used"], use] if use else list(state["used"])
        state = {**state, "lines": lines, "used": used, "undo": undo}
        text = "\n\n".join([state["notice"], "\n".join(lines)]) if lines else state["notice"]
        buttons = notice_buttons(self.services, row, state["notice"], state=state)
        assert event.button is not None
        message_id = event.button.message_id
        edited = message_id is not None and await self.services.outbox.edit(
            event.member, message_id, text, buttons
        )
        if not edited and line:  # no message to redraw: say it instead
            await self._say(event, line)

    async def _say(self, event: InboundEvent, text: str) -> None:
        await self.services.outbox.send(event.member, text, priority=Priority.REPLY)
