"""Wrong actions: a 👎 on a reply marks it, and review labels it (P4).

A 👎 on one of Themi's replies (a message sent while the model was answering,
not a card or a nudge) marks that reply as the wrong thing. It's never asked
for and never answered, and it changes nothing else: not phrasing, approvals
or energy. A marked reply keeps its tools and model calls past the week's
clean-up until it's labelled.

Review happens at the command line (`themi feedback`): each marked reply with
the person's message, what Themi said, the tools it ran and the groups it was
offered. `--wrong-tool <id> <tool>` (or `none`) labels it, from the groups:

- router miss: the right tool wasn't sent (its group wasn't chosen);
- model choice: it was sent, and the model used another;
- no tool needed: it acted where it shouldn't have.

`--not-wrong <id>` clears a mark. Each label prints a `cases.json` stub, so a
real mistake becomes an eval case. The message comes from the stored
conversation; nothing new is kept for it.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from themi import clock
from themi.channels.events import InboundEvent
from themi.core.reactions import CARDS
from themi.core.services import Services
from themi.core.tools import TOOL_GROUPS, TWINS
from themi.localtime import to_utc_iso
from themi.storage.db import Database

WRONG = "👎"
Label = Literal["router_miss", "model_choice", "no_tool_needed", "not_wrong"]
LABEL_WORDS = {
    "router_miss": "router miss",
    "model_choice": "model choice",
    "no_tool_needed": "no tool needed",
    "not_wrong": "not wrong",
}
NO_TOOL = "none"
WEEK = timedelta(days=7)


class ReviewError(ValueError):
    pass


def reply_for_message(db: Database, member_id: int, telegram_message_id: int) -> int | None:
    """The model reply that sent this message, if it was one (not a card or a nudge)."""
    row = db.one(
        "SELECT reply_id, kind FROM outbox WHERE member_id = ? AND telegram_message_id = ? "
        "AND status = 'sent' ORDER BY id DESC LIMIT 1",
        (member_id, telegram_message_id),
    )
    if row is None or row["reply_id"] is None or row["kind"] in CARDS:
        return None
    return int(row["reply_id"])


class WrongReplies:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def install(self) -> None:
        self.services.reaction_handlers.append(self.on_reaction)

    async def on_reaction(self, event: InboundEvent) -> None:
        assert event.reaction is not None
        if WRONG not in event.reaction.added:
            return
        reply_id = reply_for_message(self.db, event.member.id, event.reaction.message_id)
        if reply_id is not None:
            self.db.execute(
                "UPDATE replies SET marked_at = ? WHERE id = ? AND marked_at IS NULL",
                (to_utc_iso(clock.now()), reply_id),
            )


def was_sent(tool: str, groups: tuple[str, ...], added: tuple[str, ...] = ()) -> bool:
    """Whether a reply that was offered these groups (and added these) had the tool. A twin
    set travels whole (P6)."""
    offered = {"core", *groups, *added}
    if TOOL_GROUPS.get(tool, "core") in offered:
        return True
    return any(
        tool in twins.tools and any(TOOL_GROUPS.get(t, "core") in offered for t in twins.tools)
        for twins in TWINS
    )


def decide(tool: str, groups: tuple[str, ...], added: tuple[str, ...] = ()) -> Label:
    if tool == NO_TOOL:
        return "no_tool_needed"
    return "model_choice" if was_sent(tool, groups, added) else "router_miss"


@dataclass(frozen=True)
class MarkedReply:
    id: int
    member: str
    started_at: datetime
    message: str  # what the person said
    said: tuple[str, ...]  # what Themi sent
    tools: tuple[str, ...]
    groups: tuple[str, ...] | None  # None: an older reply that didn't record them
    groups_added: tuple[str, ...]
    label: Label | None
    right_tool: str | None


class ReplyReview:
    """Marked replies, for `themi feedback` and the Reply times page. Works on the database
    alone, so the CLI needs no running Themi."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, reply_id: int) -> MarkedReply | None:
        row = self.db.one(
            "SELECT r.*, m.name FROM replies r LEFT JOIN members m ON m.id = r.member_id "
            "WHERE r.id = ?",
            (reply_id,),
        )
        return self._reply(row) if row else None

    def unlabelled(self) -> list[MarkedReply]:
        rows = self.db.query(
            "SELECT r.*, m.name FROM replies r LEFT JOIN members m ON m.id = r.member_id "
            "WHERE r.marked_at IS NOT NULL AND r.labelled_at IS NULL ORDER BY r.id"
        )
        return [self._reply(r) for r in rows]

    def label(self, reply_id: int, tool: str | None) -> tuple[MarkedReply, dict[str, Any] | None]:
        """Label a marked reply: `tool` is what it should have used ('none' for no tool), or
        None for not wrong. Returns the reply and, unless it wasn't wrong, a case stub."""
        reply = self.get(reply_id)
        if reply is None or not self._marked(reply_id):
            raise ReviewError(f"Reply {reply_id} isn't marked.")
        if tool is None:
            label: Label = "not_wrong"
        elif reply.groups is None:
            raise ReviewError(f"Reply {reply_id} is from before the groups were recorded.")
        else:
            label = decide(tool, reply.groups, reply.groups_added)
        self.db.execute(
            "UPDATE replies SET label = ?, right_tool = ?, labelled_at = ? WHERE id = ?",
            (label, tool, to_utc_iso(clock.now()), reply_id),
        )
        labelled = self.get(reply_id)
        assert labelled is not None
        return labelled, None if tool is None else case_stub(labelled, tool)

    def week(self) -> tuple[int, Counter[str]]:
        """Replies marked in the last week, and their labels so far."""
        rows = self.db.query(
            "SELECT label FROM replies WHERE marked_at >= ?",
            (to_utc_iso(clock.now() - WEEK),),
        )
        return len(rows), Counter(r["label"] for r in rows if r["label"])

    def _marked(self, reply_id: int) -> bool:
        return bool(
            self.db.one("SELECT 1 FROM replies WHERE id = ? AND marked_at IS NOT NULL", (reply_id,))
        )

    def _reply(self, row: dict[str, Any]) -> MarkedReply:
        reply_id = row["id"]
        message = self.db.one(
            "SELECT text FROM message_log WHERE member_id = ? AND direction = 'in' "
            "AND kind NOT IN ('reaction', 'edit') AND created_at <= ? ORDER BY id DESC LIMIT 1",
            (row["member_id"], row["started_at"]),
        )
        marks = ", ".join("?" for _ in CARDS)
        said = self.db.query(
            f"SELECT COALESCE(sent_text, text) AS text FROM outbox WHERE reply_id = ? "
            f"AND kind NOT IN ({marks}) ORDER BY id",
            (reply_id, *CARDS),
        )
        tools = self.db.query(
            "SELECT name FROM reply_tools WHERE reply_id = ? ORDER BY id", (reply_id,)
        )
        return MarkedReply(
            id=reply_id,
            member=row["name"] or "someone",
            started_at=datetime.fromisoformat(row["started_at"]),
            message=message["text"] if message else "",
            said=tuple(r["text"] for r in said),
            tools=tuple(t["name"] for t in tools),
            groups=_names(row["groups"]),
            groups_added=_names(row["groups_added"]) or (),
            label=row["label"],
            right_tool=row["right_tool"],
        )


def case_stub(reply: MarkedReply, tool: str) -> dict[str, Any]:
    """An eval case for `tests/evals/cases.json`: the person's message, and what it should
    have done."""
    wrong = sorted({t for t in reply.tools if t not in (tool, "more_tools")})
    stub: dict[str, Any] = {
        "id": f"review-{reply.id}",
        "category": "from_review",
        "message": reply.message,
        "from": reply.member,
        "expect": [] if tool == NO_TOOL else [tool],
    }
    if wrong:
        stub["forbid"] = wrong
    return stub


def report(replies: list[MarkedReply], timezone: str) -> str:
    """The marked replies, for `themi feedback`."""
    if not replies:
        return ""
    lines = [
        "# Replies marked wrong (👎)",
        "",
        "Label each: `themi feedback --wrong-tool <id> <tool>` (the tool it should have used, "
        "or `none`), or `themi feedback --not-wrong <id>`.",
    ]
    for reply in replies:
        when = reply.started_at.astimezone(ZoneInfo(timezone)).strftime("%a %d %b %H:%M")
        groups = (
            "not recorded"
            if reply.groups is None
            else ", ".join(("core", *reply.groups))
            + (f"; then {', '.join(reply.groups_added)}" if reply.groups_added else "")
        )
        lines += [
            "",
            f"## Reply {reply.id}, to {reply.member}, {when}",
            "",
            f"> {reply.message}",
            "",
            *(f"Themi: {text}" for text in reply.said),
            "",
            f"Tools run: {', '.join(reply.tools) or 'none'}. Groups offered: {groups}.",
        ]
    return "\n".join(lines) + "\n"


def stub_text(stub: dict[str, Any]) -> str:
    return json.dumps(stub, indent=2, ensure_ascii=False)


def _names(text: str | None) -> tuple[str, ...] | None:
    return None if text is None else tuple(n for n in text.split(",") if n)
