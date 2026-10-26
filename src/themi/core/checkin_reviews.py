"""Asking now and then whether a check-in is helping (idea #13, Erin, 2026-10-26).

Check-ins are habits (the water one) and Themi's check-in tasks (a run on set
days). After a check-in has gone out a few times (4 by default, or what the
person chose for it), Themi asks once whether it's helping:

- Helpful: the next ask waits twice as long; after three, no more asking.
- Not really: Themi offers to stop the check-in, or keep it as it is.
- Let's talk later: the same wait again, then it asks again.
- Stop asking: never asks about that check-in again.

Asking can be turned off for one check-in, or for all of a person's check-ins
(a setting, or in chat with `set_check_in_reviews`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from themi import clock
from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core.services import Services
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

DEFAULT_EVERY = 4  # check-ins before the first ask ("at least 3-4")
DONE_AFTER = 3  # "helpful" answers before asking stops
MAX_EVERY = 64
ASK_TEXT = 'Check-in review: is "{name}" helping?'
ANSWERS = {
    "helpful": "Helpful",
    "not_really": "Not really",
    "later": "Let's talk later",
    "stop_asking": "Stop asking",
}
HELPFUL_TEXT = "Good to hear. I'll ask again in a while."
HELPFUL_DONE_TEXT = "Good to hear. It stays, and I won't ask about it again."
NOT_REALLY_TEXT = 'Thanks for saying. Stop "{name}", or keep it as it is?'
LATER_TEXT = "Sure, I'll ask again later."
STOP_ASKING_TEXT = 'I won\'t ask about "{name}" again.'
STOPPED_TEXT = 'Stopped: "{name}".'
KEPT_TEXT = 'Keeping "{name}" as it is.'


@dataclass(frozen=True)
class CheckIn:
    kind: str  # habit or task
    ref_id: int
    member_id: int
    name: str


class CheckinReviews:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.button_handlers["review"] = self.on_button
        self.services.tools.register(set_check_in_reviews)

    # ----- which check-ins, and how many so far ---------------------------------------------

    def check_ins(self, member_id: int | None = None) -> list[CheckIn]:
        found = [
            CheckIn("habit", r["id"], r["member_id"], _capital(r["idea"]))
            for r in self.db.query("SELECT * FROM habits WHERE status = 'active'")
        ]
        found += [
            CheckIn("task", r["id"], r["assignee"], r["title"])
            for r in self.db.query(
                "SELECT * FROM tasks WHERE check_in = 1 AND status IN ('open', 'snoozed') "
                "AND assignee IS NOT NULL"
            )
        ]
        return [c for c in found if member_id is None or c.member_id == member_id]

    def _total(self, kind: str, ref_id: int) -> int:
        if kind == "habit":
            return self.db.scalar("SELECT check_ins FROM habits WHERE id = ?", (ref_id,)) or 0
        return self.db.scalar("SELECT COUNT(*) FROM task_runs WHERE task_id = ?", (ref_id,))

    def _row(self, check_in: CheckIn) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM checkin_reviews WHERE kind = ? AND ref_id = ?",
            (check_in.kind, check_in.ref_id),
        )
        if row is not None:
            return row
        self.db.execute(  # counting starts now: earlier check-ins don't count
            "INSERT INTO checkin_reviews (kind, ref_id, member_id, every, seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                check_in.kind,
                check_in.ref_id,
                check_in.member_id,
                DEFAULT_EVERY,
                self._total(check_in.kind, check_in.ref_id),
            ),
        )
        return self._row(check_in)

    # ----- asking ------------------------------------------------------------------------

    async def run(self) -> int:
        """Scheduler job: ask about each check-in that's gone out enough times since the
        last ask. Returns how many were asked."""
        asked = 0
        for check_in in self.check_ins():
            row = self._row(check_in)
            member = self.store.get_member(check_in.member_id)
            if row["state"] != "on" or row["asked_at"] or not member.checkin_reviews:
                continue
            if self._total(check_in.kind, check_in.ref_id) - row["seen"] < row["every"]:
                continue
            await self.services.outbox.send(
                member,
                ASK_TEXT.format(name=check_in.name),
                priority=Priority.NORMAL,
                kind="review",
                buttons=[
                    Button(words, "review", {"review": row["id"], "answer": answer})
                    for answer, words in ANSWERS.items()
                ],
            )
            self.db.execute(
                "UPDATE checkin_reviews SET asked_at = ? WHERE id = ?",
                (to_utc_iso(clock.now()), row["id"]),
            )
            asked += 1
        return asked

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        review = self.db.one(
            "SELECT * FROM checkin_reviews WHERE id = ?", (int(event.button.payload["review"]),)
        )
        if review is None:
            return
        name = self._name(review)
        text, buttons = await self._answer(
            review, str(event.button.payload["answer"]), name, event.member
        )
        if event.button.message_id is not None:
            await self.services.outbox.edit(event.member, event.button.message_id, text, buttons)

    async def _answer(
        self, review: dict[str, Any], answer: str, name: str, member: Member
    ) -> tuple[str, list[Button]]:
        total = self._total(review["kind"], review["ref_id"])
        rid = review["id"]
        if answer == "helpful":
            yeses = review["yeses"] + 1
            state = "done" if yeses >= DONE_AFTER else "on"
            self.db.execute(
                "UPDATE checkin_reviews SET yeses = ?, every = ?, seen = ?, asked_at = NULL, "
                "state = ? WHERE id = ?",
                (yeses, min(review["every"] * 2, MAX_EVERY), total, state, rid),
            )
            return (HELPFUL_DONE_TEXT if state == "done" else HELPFUL_TEXT), []
        if answer == "later":
            self._settle(rid, total)
            return LATER_TEXT, []
        if answer == "stop_asking":
            self.db.execute(
                "UPDATE checkin_reviews SET state = 'off', asked_at = NULL WHERE id = ?", (rid,)
            )
            return STOP_ASKING_TEXT.format(name=name), []
        if answer == "not_really":
            self._settle(rid, total)
            return NOT_REALLY_TEXT.format(name=name), [
                Button("Stop it", "review", {"review": rid, "answer": "stop"}),
                Button("Keep it", "review", {"review": rid, "answer": "keep"}),
            ]
        if answer == "stop":
            await self._stop(review, member)
            self.db.execute("UPDATE checkin_reviews SET state = 'off' WHERE id = ?", (rid,))
            return STOPPED_TEXT.format(name=name), []
        return KEPT_TEXT.format(name=name), []

    def _settle(self, review_id: int, total: int) -> None:
        self.db.execute(
            "UPDATE checkin_reviews SET seen = ?, asked_at = NULL WHERE id = ?", (total, review_id)
        )

    async def _stop(self, review: dict[str, Any], member: Member) -> None:
        if review["kind"] == "habit":
            self.db.execute(
                "UPDATE habits SET status = 'retired' WHERE id = ?", (review["ref_id"],)
            )
            log.info("Retired habit %s: not helping, said member %s", review["ref_id"], member.id)
            return
        board = self.services.taskboard
        assert board is not None
        await board.cancel(review["ref_id"], member)

    def _name(self, review: dict[str, Any]) -> str:
        if review["kind"] == "habit":
            idea = self.db.scalar("SELECT idea FROM habits WHERE id = ?", (review["ref_id"],))
            return _capital(str(idea))
        return str(self.db.scalar("SELECT title FROM tasks WHERE id = ?", (review["ref_id"],)))


def _capital(text: str) -> str:
    return f"{text[:1].upper()}{text[1:]}"


@tool(
    "set_check_in_reviews",
    "How often Themi asks whether a check-in is helping (normally after 4 check-ins, then "
    "less and less). check_in: its name ('water', 'run'), or empty for all of this person's "
    "check-ins. after: ask after that many check-ins (0 keeps it). stop_asking: true to stop "
    "asking (for that check-in, or for all), false to ask again.",
    {
        "check_in": {"type": "string"},
        "after": {"type": "integer"},
        "stop_asking": {"type": "boolean"},
    },
)
async def set_check_in_reviews(ctx: ToolContext, args: dict[str, Any]) -> str:
    reviews = CheckinReviews(ctx.services)
    wanted = args["check_in"].strip().casefold()
    if not wanted:
        ctx.services.store.update_settings(
            ctx.member, ctx.member.id, checkin_reviews=not args["stop_asking"]
        )
        return (
            "Themi won't ask about any of their check-ins."
            if args["stop_asking"]
            else "Themi will ask now and then whether their check-ins are helping."
        )
    matches = [c for c in reviews.check_ins(ctx.member.id) if wanted in c.name.casefold()]
    if len(matches) != 1:
        names = "; ".join(c.name for c in reviews.check_ins(ctx.member.id)) or "none"
        raise ToolFailed(f"Say which check-in exactly. Theirs: {names}.")
    row = reviews._row(matches[0])
    every = args["after"] if args["after"] > 0 else row["every"]
    state = "off" if args["stop_asking"] else "on"
    ctx.services.store.db.execute(
        "UPDATE checkin_reviews SET every = ?, state = ? WHERE id = ?", (every, state, row["id"])
    )
    if args["stop_asking"]:
        return f"No more asking about the {matches[0].name} check-in."
    return f"Themi asks about the {matches[0].name} check-in after {every} check-ins."
