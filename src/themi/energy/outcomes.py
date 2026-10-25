"""What came of each message Themi started, and what that teaches the baseline.

- When a normal or low-priority message goes out, it's recorded with the hour
  of the week it was sent and a respond-by time for its kind.
- The person's next reply, tap or reaction resolves the most relevant open
  message: "acted" (a "not now", 💤 or snooze button: "snoozed").
- Silence past the respond-by time is "ignored" (a scheduler job).
- Each outcome nudges the baseline for that hour toward a target: acted 75,
  snoozed 45, ignored 25. The step is 1/(n+1), never below 0.1, so early
  outcomes move it quickly and later ones keep it current without swinging it.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Literal

from themi import clock
from themi.accounts import AccountStore, Member
from themi.channels.events import InboundEvent
from themi.energy.model import hour_of_week, prior
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

Outcome = Literal["acted", "snoozed", "ignored"]
TARGETS: dict[Outcome, float] = {"acted": 75.0, "snoozed": 45.0, "ignored": 25.0}
LEARNING_FLOOR = 0.1
DEFAULT_TIMEOUT = timedelta(hours=3)
TIMEOUTS = {
    "approval": timedelta(hours=6),
    "rule": timedelta(hours=12),
    "meal": timedelta(hours=2),
    "laundry": timedelta(hours=3),
    "task": timedelta(hours=8),
    "maintenance": timedelta(hours=24),
    "habit": timedelta(hours=12),
    "relay": timedelta(hours=8),
}
SNOOZE_WORDS = frozenset({"not now", "later", "maybe later", "not yet", "💤"})
SNOOZE_REACTIONS = frozenset({"💤", "⏰"})


class OutcomeTracker:
    def __init__(self, store: AccountStore) -> None:
        self.store = store
        self.db = store.db

    @property
    def timezone(self) -> str:
        family = self.store.get_family()
        return family.timezone if family else "UTC"

    # ----- recording ----------------------------------------------------------

    def on_sent(self, row: dict[str, Any], message_id: int | None) -> None:
        """Outbox listener: a proactive message just went out."""
        if row["priority"] not in ("normal", "low"):
            return
        sent_at = clock.now()
        self.db.execute(
            "INSERT OR IGNORE INTO prompt_outcomes (member_id, outbox_id, telegram_message_id, "
            "kind, sent_at, hour_of_week, respond_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["member_id"],
                row["id"],
                message_id,
                row["kind"],
                to_utc_iso(sent_at),
                hour_of_week(sent_at, self.timezone),
                to_utc_iso(sent_at + TIMEOUTS.get(row["kind"], DEFAULT_TIMEOUT)),
            ),
        )

    def observe(self, member: Member, event: InboundEvent) -> Outcome | None:
        """An inbound event resolves the open message it answers (or the latest one)."""
        now = to_utc_iso(clock.now())
        target_message = None
        if event.kind == "button" and event.button is not None:
            target_message = event.button.message_id
        elif event.kind == "reaction" and event.reaction is not None:
            target_message = event.reaction.message_id
        row = None
        if target_message is not None:
            row = self.db.one(
                "SELECT * FROM prompt_outcomes WHERE member_id = ? AND outcome IS NULL "
                "AND telegram_message_id = ? AND respond_by > ?",
                (member.id, target_message, now),
            )
        if row is None:
            row = self.db.one(
                "SELECT * FROM prompt_outcomes WHERE member_id = ? AND outcome IS NULL "
                "AND respond_by > ? ORDER BY sent_at DESC LIMIT 1",
                (member.id, now),
            )
        if row is None:
            return None
        outcome: Outcome = "snoozed" if _is_snooze(event) else "acted"
        self._resolve(row, outcome)
        return outcome

    def expire(self) -> int:
        """Messages nobody responded to in time count as ignored."""
        rows = self.db.query(
            "SELECT * FROM prompt_outcomes WHERE outcome IS NULL AND respond_by <= ?",
            (to_utc_iso(clock.now()),),
        )
        for row in rows:
            self._resolve(row, "ignored")
        return len(rows)

    # ----- learning -----------------------------------------------------------

    def _resolve(self, row: dict[str, Any], outcome: Outcome) -> None:
        self.db.execute(
            "UPDATE prompt_outcomes SET outcome = ?, resolved_at = ? WHERE id = ?",
            (outcome, to_utc_iso(clock.now()), row["id"]),
        )
        self.learn(row["member_id"], row["hour_of_week"], outcome)

    def learn(self, member_id: int, hour: int, outcome: Outcome) -> float:
        """Move that hour's baseline toward the outcome's target. Returns the new mean."""
        cell = self.db.one(
            "SELECT mean, n FROM energy_baseline WHERE member_id = ? AND hour_of_week = ?",
            (member_id, hour),
        )
        mean, n = (cell["mean"], cell["n"]) if cell else (prior(hour), 0)
        rate = max(LEARNING_FLOOR, 1 / (n + 1))
        new_mean = mean + rate * (TARGETS[outcome] - mean)
        self.db.execute(
            "INSERT INTO energy_baseline (member_id, hour_of_week, mean, n, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(member_id, hour_of_week) DO UPDATE SET "
            "mean = excluded.mean, n = excluded.n, updated_at = excluded.updated_at",
            (member_id, hour, new_mean, n + 1, to_utc_iso(clock.now())),
        )
        return new_mean

    def history(self, member_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT kind, sent_at, outcome FROM prompt_outcomes WHERE member_id = ? ORDER BY id",
            (member_id,),
        )

    def recent_rate(self, member_id: int, days: int = 14) -> float | None:
        """Share of recent proactive messages acted on (None if there aren't any)."""
        since = to_utc_iso(clock.now() - timedelta(days=days))
        rows = self.db.query(
            "SELECT outcome FROM prompt_outcomes WHERE member_id = ? AND outcome IS NOT NULL "
            "AND sent_at >= ?",
            (member_id, since),
        )
        if not rows:
            return None
        return sum(1 for r in rows if r["outcome"] == "acted") / len(rows)


def _is_snooze(event: InboundEvent) -> bool:
    if event.kind == "button" and event.button is not None:
        decision = str(event.button.payload.get("decision", ""))
        return decision == "snooze" or event.button.label.lower() in SNOOZE_WORDS
    if event.kind == "reaction" and event.reaction is not None:
        return bool(set(event.reaction.added) & SNOOZE_REACTIONS)
    return event.text.strip().lower().rstrip("!. ") in SNOOZE_WORDS
