"""Bug reports and ideas from the chat: /bug, /idea and the `log_feedback` tool.

Family testing turns into work items. Each report keeps a snapshot of what was
going on when it was sent, so it can be looked into later without asking:

- the message the person replied to (Telegram's Reply), if any
- the recent conversation, what's waiting on them, their settings and pauses
- their AI backend for conversation (never keys), Themi's version
- Themi's recent log lines, redacted

No energy numbers go in: those stay inside the energy package.

`themi feedback` prints the new reports as Markdown to paste into a Claude
session, and `themi feedback --done <id>...` marks them reviewed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from themi import __version__, clock
from themi.accounts import Member
from themi.ai.settings import AITask
from themi.channels.events import InboundEvent
from themi.channels.outbox import Priority
from themi.core.tools import ToolContext, tool
from themi.localtime import to_local, to_utc_iso
from themi.logs import recent_logs, redact
from themi.storage.db import Database

if TYPE_CHECKING:
    from themi.core.services import Services

Kind = Literal["bug", "idea"]
CONVERSATION_MESSAGES = 30
LOG_LINES = 60

THANKS = {
    "bug": "Noted, thanks. Bug report #{id} is saved with our last few messages, so it can be "
    "looked into.",
    "idea": "Love it. Idea #{id} is saved, along with our last few messages for context.",
}
HOW_TO = {
    "bug": "Happy to note it down. /bug followed by a few words works, for example: /bug the "
    "grocery list answer was wrong. Using Reply on the message in question helps too.",
    "idea": "Happy to note it down. /idea followed by a few words works, for example: /idea a "
    "weekly summary on Sundays.",
}
NAMES = {"bug": "Bug", "idea": "Idea"}


@dataclass(frozen=True)
class FeedbackItem:
    id: int
    member_id: int | None
    kind: Kind
    text: str
    context: dict[str, Any]
    status: str
    created_at: datetime


class FeedbackBook:
    """Storage and the Markdown report. Needs only the database, so the CLI can use it."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, member_id: int, kind: Kind, text: str, context: dict[str, Any]) -> int:
        return self.db.execute(
            "INSERT INTO feedback (member_id, kind, text, context, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (member_id, kind, text.strip(), json.dumps(context), to_utc_iso(clock.now())),
        )

    def items(self, include_reviewed: bool = False) -> list[FeedbackItem]:
        where = "" if include_reviewed else "WHERE status = 'new'"
        rows = self.db.query(f"SELECT * FROM feedback {where} ORDER BY created_at, id")
        return [
            FeedbackItem(
                r["id"],
                r["member_id"],
                r["kind"],
                r["text"],
                json.loads(r["context"]),
                r["status"],
                datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def mark_reviewed(self, ids: Sequence[int]) -> int:
        if not ids:
            return 0
        marks = ", ".join("?" for _ in ids)
        return self.db.update(
            f"UPDATE feedback SET status = 'reviewed', reviewed_at = ? "
            f"WHERE status = 'new' AND id IN ({marks})",
            (to_utc_iso(clock.now()), *ids),
        )

    def report(self, items: Sequence[FeedbackItem]) -> str:
        if not items:
            return "No new feedback.\n"
        bugs = sum(1 for i in items if i.kind == "bug")
        lines = [
            "# Themi feedback from the family chat",
            "",
            f"{bugs} bug report(s) and {len(items) - bugs} idea(s), oldest first. Each was sent "
            "from Telegram with /bug, /idea or in plain words, and carries a snapshot of the "
            "conversation and Themi's state when it was sent. Times are the family's local time.",
        ]
        for item in items:
            lines += ["", *_item_lines(item)]
        return "\n".join(lines) + "\n"


def _item_lines(item: FeedbackItem) -> list[str]:
    ctx = item.context
    who = ctx.get("member", {}).get("name", "someone")
    status = "" if item.status == "new" else f" ({item.status})"
    lines = [
        f"## {NAMES[item.kind]} #{item.id} from {who}, {ctx.get('local_time', '')}{status}",
        "",
        *(f"> {line}" for line in item.text.splitlines() or [""]),
        "",
        f"Sent via {ctx.get('via', 'chat')}. Themi {ctx.get('version', '?')}.",
    ]
    replied = ctx.get("replied_to")
    if replied:
        lines += ["", f"**In reply to** this message ({replied['at']}, {replied['kind']}):"]
        lines += [f"> {line}" for line in replied["text"].splitlines()]
    if ctx.get("conversation"):
        lines += ["", "**Recent conversation:**", "", "```"]
        for m in ctx["conversation"]:
            speaker = who if m["direction"] == "in" else "Themi"
            kind = "" if m["kind"] == "chat" else f" ({m['kind']})"
            text = m["text"].replace("\n", "\n    ")
            lines.append(f"[{m['at']}] {speaker}{kind}: {text}")
        lines.append("```")
    if ctx.get("open_items"):
        lines += ["", "**Open items:**", *(f"- {i}" for i in ctx["open_items"])]
    settings = ctx.get("settings")
    if settings:
        lines += ["", "**Settings:** " + "; ".join(f"{k}: {v}" for k, v in settings.items())]
    if ctx.get("ai"):
        backends = ", ".join(
            f"{b['label']} ({b['kind']}, {b['model']}, key {'set' if b['has_key'] else 'missing'})"
            for b in ctx["ai"]
        )
        lines += ["", f"**AI for conversation:** {backends}"]
    if ctx.get("log"):
        lines += ["", f"**Themi log** (last {len(ctx['log'])} lines):", "", "```"]
        lines += ctx["log"]
        lines.append("```")
    return lines


class FeedbackChat:
    """The chat side: commands, the tool, and the snapshot taken with each report."""

    def __init__(self, services: Services) -> None:
        self.services = services
        self.book = FeedbackBook(services.store.db)

    def install(self) -> None:
        s = self.services
        s.add_event_command("/bug", self.on_bug, "Report something that went wrong")
        s.add_event_command("/idea", self.on_idea, "Suggest an improvement to Themi")
        s.tools.register(log_feedback)
        s.feedback = self

    async def on_bug(self, event: InboundEvent, argument: str) -> None:
        await self._on_command(event, argument, "bug")

    async def on_idea(self, event: InboundEvent, argument: str) -> None:
        await self._on_command(event, argument, "idea")

    async def _on_command(self, event: InboundEvent, argument: str, kind: Kind) -> None:
        member = self.services.store.get_member(event.member.id)
        if not argument:
            await self.services.outbox.send(member, HOW_TO[kind], priority=Priority.REPLY)
            return
        item_id = self.record(member, kind, argument, f"/{kind}", event.reply_to_message_id)
        await self.services.outbox.send(
            member, THANKS[kind].format(id=item_id), priority=Priority.REPLY
        )

    def record(
        self,
        member: Member,
        kind: Kind,
        text: str,
        via: str,
        reply_to_message_id: int | None = None,
    ) -> int:
        context = self.snapshot(member, via, reply_to_message_id)
        return self.book.record(member.id, kind, redact(text), context)

    def snapshot(
        self, member: Member, via: str, reply_to_message_id: int | None = None
    ) -> dict[str, Any]:
        s = self.services
        family = s.store.get_family()
        timezone = family.timezone if family else "UTC"

        def local(moment: datetime) -> str:
            return to_local(moment, timezone).strftime("%a %d %b %Y %H:%M %Z")

        conversation = [
            {
                "at": to_local(m.created_at, timezone).strftime("%a %H:%M"),
                "direction": m.direction,
                "kind": m.kind,
                "text": redact(m.text),  # no sign-in links or keys in a report
            }
            for m in s.store.recent_messages(member.id, CONVERSATION_MESSAGES)
        ]
        return {
            "version": __version__,
            "via": via,
            "captured_at": to_utc_iso(clock.now()),
            "local_time": local(clock.now()),
            "member": {"id": member.id, "name": member.name, "role": member.role.value},
            "replied_to": self._replied_to(member, reply_to_message_id, timezone),
            "conversation": conversation,
            "open_items": [item.summary for item in s.open_items(member)],
            "settings": self._settings(member, timezone),
            "ai": self._ai(member),
            "log": recent_logs.tail(LOG_LINES),
        }

    def _replied_to(
        self, member: Member, message_id: int | None, timezone: str
    ) -> dict[str, str] | None:
        if message_id is None:
            return None
        row = self.services.store.db.one(
            "SELECT * FROM message_log WHERE member_id = ? AND telegram_message_id = ? "
            "AND kind != 'edit' ORDER BY id DESC LIMIT 1",  # newest: dev runs reuse numbers
            (member.id, message_id),
        )
        if row is None:
            return {"at": "?", "kind": "unknown", "text": f"(message {message_id}, not in the log)"}
        moment = to_local(datetime.fromisoformat(row["created_at"]), timezone)
        return {
            "at": moment.strftime("%a %H:%M"),
            "kind": f"{'from Themi' if row['direction'] == 'out' else 'their own'} {row['kind']}",
            "text": redact(row["text"]),
        }

    def _settings(self, member: Member, timezone: str) -> dict[str, str]:
        pauses = self.services.outbox.pauses.active(member)
        return {
            "quiet hours": f"{member.quiet_start:%H:%M}-{member.quiet_end:%H:%M}",
            "daily message limit": str(member.daily_limit),
            "phrasing": member.phrasing
            + (f" ({member.phrasing_notes})" if member.phrasing_notes else ""),
            "gentle phrasing": f"strength {member.pda_strength}" if member.pda_enabled else "off",
            "check-in reviews": "on" if member.checkin_reviews else "off",
            "chores on the chart at a time": str(member.chart_limit or "no limit")
            + ("" if member.chart_counts_shared else " (shared chores don't count)"),
            "morning summary": member.morning_summary.strftime("%H:%M")
            if member.morning_summary
            else "off",
            "leave heads-up": f"on, {member.getting_ready_minutes} min to get ready"
            if member.leave_heads_up
            else "off",
            "calendar details seen by": "them only"
            if member.calendar_details == "me"
            else "them and their partner",
            "tracking": ", ".join(
                f"{k} {'on' if v else 'off'}" for k, v in member.tracking.items()
            ),
            "pauses": ", ".join(
                f"{p.topic} until {to_local(p.until, timezone):%a %H:%M}" for p in pauses
            )
            or "none",
            "busy times": "; ".join(b.label() for b in member.busy_times) or "none",
            "timezone": timezone,
        }

    def _ai(self, member: Member) -> list[dict[str, Any]]:
        ai = self.services.ai_settings
        backends = []
        for entry in ai.chain(member.id, AITask.CONVERSATION):
            backend = ai.get_backend(entry.backend_id)
            backends.append(
                {
                    "label": backend.label,
                    "kind": backend.kind,
                    "model": entry.model or backend.model,
                    "has_key": backend.has_key,
                }
            )
        return backends


@tool(
    "log_feedback",
    "Save a bug report or an idea about Themi itself, when the person says something went "
    "wrong with Themi or suggests how Themi could work better ('that's a bug', 'it would be "
    "nice if you...'). Not for household tasks or reminders. The recent conversation is saved "
    "with it automatically.",
    {
        "kind": {"type": "string", "enum": ["bug", "idea"]},
        "summary": {
            "type": "string",
            "description": "What went wrong or what they'd like, in their words where possible.",
        },
    },
)
async def log_feedback(ctx: ToolContext, args: dict[str, Any]) -> str:
    chat = ctx.services.feedback
    if chat is None:
        return "Feedback isn't set up on this server."
    item_id = chat.record(ctx.member, args["kind"], args["summary"], "plain words (log_feedback)")
    return f"Saved as {NAMES[args['kind']].lower()} #{item_id}. Tell them it's noted."


__all__ = ["FeedbackBook", "FeedbackChat", "FeedbackItem", "log_feedback"]
