"""The Shadow Calendar's capacity model: how much someone likely has in the tank.

    capacity (0-100) = baseline for this hour of the week
                     + recent signals, each fading with the person's recovery speed

- The baseline is learned per member and hour of the week (prompt 19). Until a
  cell has data, a gentle prior day-curve stands in: low overnight, rising
  through the morning, a dip mid-afternoon and a wind-down in the evening.
  Learned cells blend with the prior, so a few outcomes don't swing it.
- A signal is worth `SIGNAL_POINTS` per unit (-3 very draining ... +3 very
  restoring), halving every `recovery_hours` (each member's own setting).
- Signals from an input the person has switched off are ignored, including
  ones recorded before they switched it off.

The number never leaves this module except as words ("seems like a low
stretch"); nobody is ever shown a score.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from themi import clock
from themi.accounts import AccountStore, Member
from themi.localtime import to_local, to_utc_iso

SIGNAL_POINTS = 8.0
SIGNAL_WINDOW = timedelta(hours=72)  # older signals have faded to nothing that matters
PRIOR_WEIGHT = 3  # a learned cell needs a few outcomes before it outweighs the prior

# Local hour -> prior capacity, before anything is learned.
PRIOR_CURVE = (
    20,
    20,
    20,
    20,
    20,
    22,  # 00-05
    30,
    40,
    50,
    55,
    62,
    65,  # 06-11
    62,
    58,
    55,
    57,
    60,
    58,  # 12-17
    55,
    52,
    48,
    40,
    32,
    25,  # 18-23
)

# (upper bound, words). Words only: these reach prompts and messages.
LABELS = (
    (25.0, "running low today, it seems"),
    (45.0, "seems like a low stretch"),
    (65.0, "steady"),
    (80.0, "seems to have some energy"),
    (math.inf, "seems to be in a good stretch"),
)
NOT_TRACKED = "no read (they've turned energy tracking off)"

SOURCE_INPUT = {  # signal source -> the tracking toggle that governs it
    "text_note": "text_notes",
    "day_level": "text_notes",  # "it's a medium energy day": -1 low, 0 medium, 1 high
    "message_timing": "message_timing",
    "device_activity": "device_activity",
}


@dataclass(frozen=True)
class Signal:
    source: str
    value: float
    at: datetime


def hour_of_week(moment: datetime, timezone: str) -> int:
    local = to_local(moment, timezone)
    return local.weekday() * 24 + local.hour


def prior(hour: int) -> float:
    return float(PRIOR_CURVE[hour % 24])


def signal_effect(value: float, age: timedelta, recovery_hours: float) -> float:
    """Capacity points a signal still contributes after `age`."""
    if age < timedelta(0):
        return 0.0
    half_lives = age.total_seconds() / 3600 / max(recovery_hours, 0.1)
    return value * SIGNAL_POINTS * 0.5**half_lives


# A stated day level pulls that local day towards these, instead of adding points.
DAY_LEVEL_TARGETS = {-1: 35.0, 0: 55.0, 1: 75.0}
DAY_LEVEL_WEIGHT = 0.75


def combine(
    baseline: float,
    signals: Iterable[Signal],
    now: datetime,
    recovery_hours: float,
    timezone: str | None = None,
) -> float:
    """Baseline plus fading signals. With `timezone`, the latest day level stated earlier
    the same local day (if any) pulls the result towards its target."""
    signals = list(signals)
    total = baseline + sum(
        signal_effect(s.value, now - s.at, recovery_hours)
        for s in signals
        if s.source != "day_level"
    )
    if timezone is not None:
        today = to_local(now, timezone).date()
        levels = [
            s
            for s in signals
            if s.source == "day_level" and s.at <= now and to_local(s.at, timezone).date() == today
        ]
        if levels:
            latest = sorted(levels, key=lambda s: s.at)[-1]  # stable: ties go to the last stored
            target = DAY_LEVEL_TARGETS[round(latest.value)]
            total = DAY_LEVEL_WEIGHT * target + (1 - DAY_LEVEL_WEIGHT) * total
    return max(0.0, min(100.0, total))


def label_for(capacity: float) -> str:
    for bound, words in LABELS:
        if capacity < bound:
            return words
    return LABELS[-1][1]  # pragma: no cover - the last bound is infinite


class EnergyModel:
    def __init__(self, store: AccountStore) -> None:
        self.store = store
        self.db = store.db

    @property
    def timezone(self) -> str:
        family = self.store.get_family()
        return family.timezone if family else "UTC"

    # ----- inputs -------------------------------------------------------------

    def record(self, member: Member, source: str, value: float, note: str = "") -> bool:
        """Store a signal if the member allows that input. Returns whether it was stored."""
        if not member.tracks(SOURCE_INPUT[source]):
            return False
        bound = 1.0 if source == "day_level" else 3.0
        value = max(-bound, min(bound, value))
        self.db.execute(
            "INSERT INTO energy_signals (member_id, source, value, note, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (member.id, source, value, note[:200], to_utc_iso(clock.now())),
        )
        return True

    def observe_inbound(self, member: Member, at: datetime | None = None) -> None:
        """Reply latency: how soon someone answered the last thing Themi started.

        A quick reply suggests some energy; a very slow one, a little less. One signal
        per proactive message at most.
        """
        now = at or clock.now()
        row = self.db.one(
            "SELECT id, sent_at FROM outbox WHERE member_id = ? AND status = 'sent' "
            "AND priority IN ('normal', 'low') AND sent_at <= ? "
            "ORDER BY sent_at DESC LIMIT 1",
            (member.id, to_utc_iso(now)),
        )
        if row is None:
            return
        note = f"outbox:{row['id']}"
        if self.db.one(
            "SELECT 1 FROM energy_signals WHERE member_id = ? AND source = 'message_timing' "
            "AND note = ?",
            (member.id, note),
        ):
            return  # already counted the reply to this message
        latency = now - datetime.fromisoformat(row["sent_at"])
        if latency > timedelta(hours=12):
            return  # too long ago to say anything
        if latency <= timedelta(minutes=10):
            value = 0.5
        elif latency <= timedelta(hours=2):
            value = 0.0  # recorded anyway, so this message isn't counted twice
        else:
            value = -0.5
        self.record(member, "message_timing", value, note)

    def observe_device_activity(self, member: Member, value: float, note: str = "") -> bool:
        """Phase 2 hook: a device suggests effort (negative) or rest (positive)."""
        return self.record(member, "device_activity", value, note)

    # ----- the model ----------------------------------------------------------

    def baseline(self, member: Member, at: datetime | None = None) -> float:
        hour = hour_of_week(at or clock.now(), self.timezone)
        row = self.db.one(
            "SELECT mean, n FROM energy_baseline WHERE member_id = ? AND hour_of_week = ?",
            (member.id, hour),
        )
        if row is None or row["n"] == 0:
            return prior(hour)
        weight = row["n"] / (row["n"] + PRIOR_WEIGHT)
        return weight * row["mean"] + (1 - weight) * prior(hour)

    def signals(self, member: Member, at: datetime | None = None) -> list[Signal]:
        now = at or clock.now()
        allowed = [s for s, toggle in SOURCE_INPUT.items() if member.tracks(toggle)]
        if not allowed:
            return []
        placeholders = ", ".join("?" for _ in allowed)
        rows = self.db.query(
            f"SELECT source, value, created_at FROM energy_signals WHERE member_id = ? "
            f"AND source IN ({placeholders}) AND created_at > ? AND created_at <= ? ORDER BY id",
            (member.id, *allowed, to_utc_iso(now - SIGNAL_WINDOW), to_utc_iso(now)),
        )
        return [
            Signal(r["source"], r["value"], datetime.fromisoformat(r["created_at"])) for r in rows
        ]

    def capacity(self, member: Member, at: datetime | None = None) -> float:
        now = at or clock.now()
        member = self.store.get_member(member.id)  # recovery speed and toggles may change
        return combine(
            self.baseline(member, now),
            self.signals(member, now),
            now,
            member.recovery_hours,
            self.timezone,
        )

    def suggested_level(self, member: Member) -> str | None:
        """ "low", "medium" or "high" for a chore's level today: a level they stated today wins,
        else the estimate. None if they've switched every input off (no read)."""
        member = self.store.get_member(member.id)
        if not any(member.tracks(toggle) for toggle in SOURCE_INPUT.values()):
            return None
        now = clock.now()
        today = to_local(now, self.timezone).date()
        stated = [
            s
            for s in self.signals(member, now)
            if s.source == "day_level" and to_local(s.at, self.timezone).date() == today
        ]
        if stated:
            return {-1: "low", 0: "medium", 1: "high"}[round(stated[-1].value)]
        capacity = self.capacity(member, now)
        return "low" if capacity < 45 else "medium" if capacity < 65 else "high"

    def label(self, member: Member) -> str:
        member = self.store.get_member(member.id)
        if not any(member.tracks(toggle) for toggle in SOURCE_INPUT.values()):
            return NOT_TRACKED
        return label_for(self.capacity(member))
