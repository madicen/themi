"""P2a: why a reply takes as long as it does, and a word while it's slow.

Ideas #51 ("make Themi faster") and #55 ("internal metrics of why responses take as long
as they do"): each reply that goes to the model is timed, kept for a week like `ai_calls`.
The model calls are `ai_calls` rows tagged with the reply (`router.current_reply`); the
tools and the outbox are timed here.

Michael's idea: when a reply is still coming after `SLOW_AFTER` seconds, one short message
says so. Some of them normalize what the family wants to be able to talk about (a
low-energy day); others are plain. Never the same one twice in a row.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import statistics
from collections import Counter
from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from themi import clock
from themi.ai.router import current_reply
from themi.localtime import to_utc_iso
from themi.storage.db import Database

log = logging.getLogger(__name__)

REPLIES_KEPT = timedelta(days=7)
SLOW_AFTER = 25.0  # seconds (10 s came too soon, idea #65)
SLOW_NOTICES = (
    "I'm having a bit of a low-energy day myself. I'll answer as soon as I can.",
    "Still thinking, nearly there.",
    "My brain's a little foggy right now, so this is taking a while. The answer's coming.",
    "Taking me longer than usual today. Your answer's on its way.",
    "Going slowly on my end, the way days sometimes go. Nearly there.",
    "Still working on this one. I haven't forgotten you.",
    "Running a bit slow today. It's still coming.",
    "Some days everything takes longer, me included. Almost there.",
)


def _seconds(start: datetime) -> float:
    return round((clock.now() - start).total_seconds(), 2)


@dataclass
class ReplyTimer:
    """One reply's timings. `start()` makes its row, so the model calls can point at it."""

    db: Database
    member_id: int
    started: datetime = field(default_factory=clock.now)
    reply_id: int | None = None
    outbox_seconds: float = 0.0
    notice: str | None = None
    # P3: the tool groups sent at the start, how many tools that was, and those added later.
    groups: tuple[str, ...] | None = None
    tools_sent: int | None = None
    groups_added: tuple[str, ...] = ()
    _tools: list[tuple[str, int, datetime, float]] = field(default_factory=list)

    def start(self) -> None:
        try:
            self.reply_id = self.db.execute(
                "INSERT INTO replies (member_id, started_at) VALUES (?, ?)",
                (self.member_id, to_utc_iso(self.started)),
            )
        except sqlite3.Error:  # never lose an answer over a note about it
            log.warning("Couldn't record a reply's timing", exc_info=True)
        current_reply.set(self.reply_id)

    def route(self, groups: Iterable[str], tools_sent: int) -> None:
        self.groups, self.tools_sent = tuple(sorted(groups)), tools_sent

    def added(self, groups: Iterable[str]) -> None:
        self.groups_added = tuple(sorted(groups))

    @contextmanager
    def tool(self, name: str, after_model: int) -> Iterator[None]:
        began = clock.now()
        try:
            yield
        finally:
            self._tools.append((name, after_model, began, _seconds(began)))

    @asynccontextmanager
    async def outbox(self) -> AsyncIterator[None]:
        began = clock.now()
        try:
            yield
        finally:
            self.outbox_seconds += _seconds(began)

    def finish(self) -> None:
        current_reply.set(None)
        if self.reply_id is None:
            return
        try:
            self.db.execute(
                "UPDATE replies SET seconds = ?, outbox_seconds = ?, slow_notice = ?, "
                "groups = ?, groups_added = ?, tools_sent = ? WHERE id = ?",
                (
                    _seconds(self.started),
                    self.outbox_seconds,
                    self.notice,
                    None if self.groups is None else ",".join(self.groups),
                    None if self.groups is None else ",".join(self.groups_added),
                    self.tools_sent,
                    self.reply_id,
                ),
            )
            for name, after_model, began, seconds in self._tools:
                self.db.execute(
                    "INSERT INTO reply_tools (reply_id, name, after_model, started_at, seconds) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (self.reply_id, name, after_model, to_utc_iso(began), seconds),
                )
            self.db.execute(
                "DELETE FROM replies WHERE started_at < ?",
                (to_utc_iso(clock.now() - REPLIES_KEPT),),
            )
        except sqlite3.Error:
            log.warning("Couldn't record a reply's timing", exc_info=True)


def pick_notice(db: Database, member_id: int, rng: random.Random) -> str:
    """One of SLOW_NOTICES, not the one this person had last."""
    last = db.scalar(
        "SELECT slow_notice FROM replies WHERE member_id = ? AND slow_notice IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (member_id,),
    )
    return rng.choice([text for text in SLOW_NOTICES if text != last])


# ----- for the admin page -----------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    started_at: str
    what: str
    seconds: float
    detail: str = ""


@dataclass(frozen=True)
class Reply:
    id: int
    member_id: int
    started_at: str
    seconds: float
    model_seconds: float
    tool_seconds: float
    outbox_seconds: float
    slow_notice: str | None
    steps: tuple[Step, ...]
    groups: tuple[str, ...] | None = None  # None: from before P3
    groups_added: tuple[str, ...] = ()
    tools_sent: int | None = None
    asked_for_more: bool = False  # the model called more_tools: the groups missed


def _model_step(call: dict[str, Any]) -> Step:
    detail = [call["backend"]] if call["backend"] else []
    if call["waited"]:
        detail.append(f"waited {call['waited']:.1f} s")
    if call["retries"]:
        detail.append(f"{call['retries']} {'retry' if call['retries'] == 1 else 'retries'}")
    if not call["ok"]:
        detail.append("failed")
    what = "Model" if call["task"] == "conversation" else f"Model ({call['task']})"
    return Step(call["started_at"], what, call["seconds"], ", ".join(detail))


def _steps(calls: list[dict[str, Any]], tools: list[dict[str, Any]], outbox: float) -> list[Step]:
    """The conversation's model rounds, each followed by the tools it asked for; then the
    other calls (a gentler rewording, in the outbox) and the outbox itself."""
    steps = []
    rounds = [c for c in calls if c["task"] == "conversation"]
    for n, call in enumerate(rounds, start=1):
        steps.append(_model_step(call))
        steps += [
            Step(t["started_at"], f"Tool {t['name']}", t["seconds"])
            for t in tools
            if t["after_model"] == n
        ]
    steps += [_model_step(c) for c in calls if c["task"] != "conversation"]
    steps.append(Step("", "Outbox", outbox))
    return steps


def _names(text: str | None) -> tuple[str, ...] | None:
    return None if text is None else tuple(n for n in text.split(",") if n)


def week_of_replies(db: Database) -> list[Reply]:
    since = to_utc_iso(clock.now() - REPLIES_KEPT)
    rows = db.query("SELECT * FROM replies WHERE started_at >= ? ORDER BY id", (since,))
    calls: dict[int, list[dict[str, Any]]] = {}
    for call in db.query(
        "SELECT * FROM ai_calls WHERE reply_id IS NOT NULL AND started_at >= ? ORDER BY id",
        (since,),
    ):
        calls.setdefault(call["reply_id"], []).append(call)
    tools: dict[int, list[dict[str, Any]]] = {}
    for tool in db.query(
        "SELECT t.* FROM reply_tools t JOIN replies r ON r.id = t.reply_id "
        "WHERE r.started_at >= ? ORDER BY t.id",
        (since,),
    ):
        tools.setdefault(tool["reply_id"], []).append(tool)
    replies = []
    for row in rows:
        mine, used = calls.get(row["id"], []), tools.get(row["id"], [])
        replies.append(
            Reply(
                id=row["id"],
                member_id=row["member_id"],
                started_at=row["started_at"],
                seconds=row["seconds"],
                model_seconds=round(
                    sum(c["seconds"] for c in mine if c["task"] == "conversation"), 2
                ),
                tool_seconds=round(sum(t["seconds"] for t in used), 2),
                outbox_seconds=row["outbox_seconds"],
                slow_notice=row["slow_notice"],
                steps=tuple(_steps(mine, used, row["outbox_seconds"])),
                groups=_names(row["groups"]),
                groups_added=_names(row["groups_added"]) or (),
                tools_sent=row["tools_sent"],
                asked_for_more=any(t["name"] == "more_tools" for t in used),
            )
        )
    return replies


def medians(replies: list[Reply]) -> dict[str, float]:
    if not replies:
        return {}
    return {
        name: round(statistics.median(getattr(r, name) for r in replies), 1)
        for name in ("seconds", "model_seconds", "tool_seconds", "outbox_seconds")
    }


@dataclass(frozen=True)
class RouterNumbers:
    """P3: how well P1's word lists chose the tool groups, over replies that recorded them."""

    count: int
    missed: int  # replies where the model asked for more tools
    added_late: list[tuple[str, int]]  # groups more_tools brought in, most often first
    tools_sent: float  # median, with the first model call
    seconds_missed: float | None  # median reply time with a miss
    seconds_hit: float | None  # and without one


def router_numbers(replies: list[Reply]) -> RouterNumbers | None:
    routed = [r for r in replies if r.groups is not None]
    if not routed:
        return None

    def median_seconds(some: list[Reply]) -> float | None:
        return round(statistics.median(r.seconds for r in some), 1) if some else None

    missed = [r for r in routed if r.asked_for_more]
    return RouterNumbers(
        count=len(routed),
        missed=len(missed),
        added_late=Counter(g for r in routed for g in r.groups_added).most_common(),
        tools_sent=round(statistics.median(r.tools_sent or 0 for r in routed), 1),
        seconds_missed=median_seconds(missed),
        seconds_hit=median_seconds([r for r in routed if not r.asked_for_more]),
    )
