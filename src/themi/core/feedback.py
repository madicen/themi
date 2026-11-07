"""Bug reports and ideas from the chat: /bug, /idea and the `log_feedback` tool.

Family testing turns into work items. Each report keeps a snapshot of what was
going on when it was sent, so it can be looked into later without asking:

- the message the person replied to (Telegram's Reply), if any
- the reply it's about (that message's, else the latest): its tools, and the
  tool groups it was offered and added (P4)
- the recent conversation, what's waiting on them, their settings and pauses
- their AI backend for conversation (never keys), Themi's version
- Themi's recent log lines, redacted

No energy numbers go in: those stay inside the energy package.

`themi feedback` prints the new reports as Markdown to paste into a Claude
session, and `themi feedback --done <id>...` marks them reviewed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from themi import __version__, clock
from themi.accounts import Member
from themi.ai.settings import AITask
from themi.channels.events import InboundEvent, Picture
from themi.channels.outbox import Priority
from themi.core.tools import ToolContext, tool
from themi.core.wrong_replies import ReplyReview, reply_for_message
from themi.localtime import to_local, to_utc_iso
from themi.logs import recent_logs, redact
from themi.storage.db import Database
from themi.storage.secrets import Cipher

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
# F34o: screenshots kept with a report, encrypted.
MAX_PICTURES = 3
MAX_PICTURE_BYTES = 5 * 1024 * 1024
PICTURE_DAYS = 60
WITH_PICTURE = {1: " Your screenshot is saved with it.", 2: " Your screenshots are saved with it."}
# "that's a bug" after a picture means the picture (F34l keeps it in memory for a while).
POINTS_AT = re.compile(
    r"\b(?:that|this|it|these|those|the (?:picture|screenshot|photo|image))\b", re.IGNORECASE
)
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


@dataclass(frozen=True)
class KeptFile:
    """A report's picture, decrypted, for the operator (`themi feedback --pictures`)."""

    id: int
    feedback_id: int
    mime_type: str
    data: bytes = field(repr=False)


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

    def __init__(self, db: Database, cipher: Cipher | None = None) -> None:
        self.db = db
        self.cipher = cipher  # F34o: for the pictures; none, and none are kept

    def record(self, member_id: int, kind: Kind, text: str, context: dict[str, Any]) -> int:
        return self.db.execute(
            "INSERT INTO feedback (member_id, kind, text, context, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (member_id, kind, text.strip(), json.dumps(context), to_utc_iso(clock.now())),
        )

    def attach(self, feedback_id: int, member_id: int, pictures: Sequence[Picture]) -> int:
        """F34o: keep up to three pictures with the report, encrypted. Returns how many."""
        if self.cipher is None:
            return 0
        kept = 0
        for picture in pictures[:MAX_PICTURES]:
            if len(picture.data) > MAX_PICTURE_BYTES:
                continue
            self.db.execute(
                "INSERT INTO feedback_pictures (feedback_id, member_id, mime_type, data, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    feedback_id,
                    member_id,
                    picture.mime_type,
                    self.cipher.encrypt_bytes(picture.data),
                    to_utc_iso(clock.now()),
                ),
            )
            kept += 1
        return kept

    def picture_counts(self) -> dict[int, int]:
        rows = self.db.query(
            "SELECT feedback_id, COUNT(*) AS n FROM feedback_pictures GROUP BY feedback_id"
        )
        return {r["feedback_id"]: r["n"] for r in rows}

    def pictures(self, feedback_ids: Sequence[int]) -> list[KeptFile]:
        """The reports' pictures, decrypted (the CLI writes them to a folder)."""
        if self.cipher is None or not feedback_ids:
            return []
        marks = ", ".join("?" for _ in feedback_ids)
        rows = self.db.query(
            f"SELECT * FROM feedback_pictures WHERE feedback_id IN ({marks}) ORDER BY id",
            tuple(feedback_ids),
        )
        return [
            KeptFile(
                r["id"], r["feedback_id"], r["mime_type"], self.cipher.decrypt_bytes(r["data"])
            )
            for r in rows
        ]

    def forget_pictures(self, days: int = PICTURE_DAYS) -> int:
        """F34o: pictures go after 60 days, reviewed or not."""
        cutoff = to_utc_iso(clock.now() - timedelta(days=days))
        return self.db.update("DELETE FROM feedback_pictures WHERE created_at < ?", (cutoff,))

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
        marked = self.db.update(
            f"UPDATE feedback SET status = 'reviewed', reviewed_at = ? "
            f"WHERE status = 'new' AND id IN ({marks})",
            (to_utc_iso(clock.now()), *ids),
        )
        # F34o: a reviewed report's pictures are deleted.
        self.db.execute(f"DELETE FROM feedback_pictures WHERE feedback_id IN ({marks})", tuple(ids))
        return marked

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
        counts = self.picture_counts()
        for item in items:
            lines += ["", *_item_lines(item, counts.get(item.id, 0))]
        return "\n".join(lines) + "\n"


def picture_name(item_id: int, kept: KeptFile, n: int) -> str:
    """The file a report's picture is written to: "bug-182-1.png"."""
    return f"report-{item_id}-{n}.{EXTENSIONS.get(kept.mime_type, 'img')}"


def _item_lines(item: FeedbackItem, pictures: int = 0) -> list[str]:
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
    if pictures:  # F34o
        files = ", ".join(f"report-{item.id}-{n}.*" for n in range(1, pictures + 1))
        lines += [
            "",
            f"**Screenshots:** {pictures} sent with it ({files}); `themi feedback --pictures "
            "<folder>` writes them there.",
        ]
    replied = ctx.get("replied_to")
    if replied:
        lines += ["", f"**In reply to** this message ({replied['at']}, {replied['kind']}):"]
        lines += [f"> {line}" for line in replied["text"].splitlines()]
    reply = ctx.get("reply")
    if reply:
        groups = (
            "not recorded" if reply["groups"] is None else ", ".join(["core", *reply["groups"]])
        )
        added = (
            f"; added later: {', '.join(reply['groups_added'])}" if reply["groups_added"] else ""
        )
        lines += [
            "",
            f"**About reply {reply['id']}:** tools run: {', '.join(reply['tools']) or 'none'}; "
            f"groups offered: {groups}{added}.",
        ]
        for n, call in enumerate(reply.get("calls", []), 1):
            said = call["result"].replace("\n", " ")
            lines.append(f"{n}. {call['name']} {call['arguments']} → {said}")
        for shaped in reply.get("shaped", []):
            before = shaped["before"].replace("\n", " ")
            after = shaped["after"].replace("\n", " ")
            lines.append(f'Gentle phrasing changed "{before}" to "{after}".')
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
        self.book = FeedbackBook(services.store.db, services.store.cipher)

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
        pictures = self.pictures_for(member, event.picture, argument)
        item_id = self.record(
            member, kind, argument, f"/{kind}", event.reply_to_message_id, pictures=pictures
        )
        if kind == "bug" and self.services.conversation is not None:  # CM1c: a miss to look at
            self.services.conversation.sidecar.mark_missed(member)
        thanks = THANKS[kind].format(id=item_id) + self._kept_words(item_id)
        await self.services.outbox.send(member, thanks, priority=Priority.REPLY)

    def pictures_for(self, member: Member, sent: Picture | None, words: str) -> list[Picture]:
        """F34o: the picture sent with the report, or, when the report points at it ("that
        got cut off"), the one they sent just before."""
        if sent is not None:
            return [sent]
        before = self.services.kept_pictures.peek(member.id)
        return [before] if before is not None and POINTS_AT.search(words) else []

    def _kept_words(self, item_id: int) -> str:
        count = self.book.picture_counts().get(item_id, 0)
        return WITH_PICTURE[min(count, 2)] if count else ""

    def record(
        self,
        member: Member,
        kind: Kind,
        text: str,
        via: str,
        reply_to_message_id: int | None = None,
        *,
        pictures: Sequence[Picture] = (),
    ) -> int:
        context = self.snapshot(member, via, reply_to_message_id)
        item_id = self.book.record(member.id, kind, redact(text), context)
        self.book.attach(item_id, member.id, pictures)  # F34o
        return item_id

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
            "reply": self._reply(member, reply_to_message_id),
            "conversation": conversation,
            "open_items": [item.summary for item in s.open_items(member)],
            "sidecar": (  # CM1c: what conversation mode's sidecar picked out lately
                s.conversation.sidecar.recent(member, 3) if s.conversation is not None else []
            ),
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

    def _reply(self, member: Member, message_id: int | None) -> dict[str, Any] | None:
        """The model reply a report is about: the one that sent the message it replies to,
        else the latest."""
        db = self.services.store.db
        reply_id = reply_for_message(db, member.id, message_id) if message_id else None
        if reply_id is None:
            reply_id = db.scalar("SELECT MAX(id) FROM replies WHERE member_id = ?", (member.id,))
        reply = ReplyReview(db).get(reply_id) if reply_id else None
        if reply is None:
            return None
        calls = db.query(  # bug #110: what each was given and said back
            "SELECT name, arguments, result FROM reply_tools WHERE reply_id = ? ORDER BY id",
            (reply.id,),
        )
        shaped = db.query(  # F30b: what the gentle-phrasing shield changed, before and after
            "SELECT text, sent_text FROM outbox WHERE reply_id = ? AND sent_text IS NOT NULL "
            "AND sent_text != text ORDER BY id",
            (reply.id,),
        )
        return {
            "id": reply.id,
            "shaped": [{"before": r["text"], "after": r["sent_text"]} for r in shaped],
            "tools": list(reply.tools),
            "calls": [c for c in calls if c["arguments"] is not None],
            "groups": None if reply.groups is None else list(reply.groups),
            "groups_added": list(reply.groups_added),
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
            "noise emails": member.noise_emails.replace("_", " "),
            "leave heads-up": f"on, {member.getting_ready_minutes} min to get ready"
            if member.leave_heads_up
            else "off",
            "set-up notes on events": "on" if member.setup_note else "off",
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
    sent = ctx.image if ctx.picture else None
    pictures = chat.pictures_for(ctx.member, sent, ctx.request_text)
    item_id = chat.record(
        ctx.member, args["kind"], args["summary"], "plain words (log_feedback)", pictures=pictures
    )
    kept = " Their screenshot is saved with it; say so." if pictures else ""
    return f"Saved as {NAMES[args['kind']].lower()} #{item_id}. Tell them it's noted.{kept}"


__all__ = ["FeedbackBook", "FeedbackChat", "FeedbackItem", "log_feedback"]
