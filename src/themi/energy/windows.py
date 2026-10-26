"""Good windows: when someone is likely to have room for a message.

Capacity is projected forward in 15-minute steps (the baseline for each
future hour plus today's signals, faded to that moment). A window is a run
of steps at or above a threshold, outside quiet hours and busy times.

The outbox asks `EnergyReceptivity.not_before()`:
- normal messages wait for a receptive window (steady or better);
- low-priority ones wait for a strong window;
- if nothing clears the bar within a day, the best moment in that day is
  used, so nothing waits forever;
- someone who has switched every energy input off is never held back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from themi.accounts import Member
from themi.channels.outbox import Priority
from themi.energy.model import SOURCE_INPUT, EnergyModel, combine, hour_of_week
from themi.localtime import in_busy_time, in_quiet_hours

STEP = timedelta(minutes=15)
HORIZON = timedelta(hours=24)
RECEPTIVE = 45.0  # "steady" or better
STRONG = 60.0


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


class Projection:
    """Capacity at future moments for one member, computed with few queries."""

    def __init__(self, model: EnergyModel, member: Member, start: datetime) -> None:
        self.model = model
        self.member = model.store.get_member(member.id)
        self.timezone = model.timezone
        self.signals = model.signals(self.member, start)
        self.blocks = model.blocks_around(self.member, start, start + HORIZON)
        self._baselines: dict[int, float] = {}

    def at(self, moment: datetime) -> float:
        hour = hour_of_week(moment, self.timezone)
        if hour not in self._baselines:
            self._baselines[hour] = self.model.baseline(self.member, moment)
        total = combine(
            self._baselines[hour], self.signals, moment, self.member.recovery_hours, self.timezone
        )
        return max(0.0, total - self.model.load(self.member, moment, self.blocks))

    def quiet(self, moment: datetime) -> bool:
        """No messages then: quiet hours or a busy time."""
        return (
            in_quiet_hours(self.member, moment, self.timezone)
            or in_busy_time(self.member, moment, self.timezone)
            or any(start <= moment < end for start, end in self.blocks)
        )


def _steps(start: datetime, horizon: timedelta) -> list[datetime]:
    return [start + STEP * i for i in range(int(horizon / STEP) + 1)]


def windows(
    model: EnergyModel,
    member: Member,
    start: datetime,
    *,
    threshold: float = RECEPTIVE,
    horizon: timedelta = HORIZON,
) -> list[Window]:
    projection = Projection(model, member, start)
    found: list[Window] = []
    open_at: datetime | None = None
    for moment in _steps(start, horizon):
        good = not projection.quiet(moment) and projection.at(moment) >= threshold
        if good and open_at is None:
            open_at = moment
        elif not good and open_at is not None:
            found.append(Window(open_at, moment))
            open_at = None
    if open_at is not None:
        found.append(Window(open_at, start + horizon))
    return found


def next_window(
    model: EnergyModel,
    member: Member,
    start: datetime,
    *,
    threshold: float = RECEPTIVE,
    horizon: timedelta = HORIZON,
) -> datetime:
    """The first good moment from `start`; failing that, the best moment within the horizon."""
    projection = Projection(model, member, start)
    best: tuple[float, datetime] | None = None
    for moment in _steps(start, horizon):
        if projection.quiet(moment):
            continue
        capacity = projection.at(moment)
        if capacity >= threshold:
            return moment
        if best is None or capacity > best[0]:
            best = (capacity, moment)
    return best[1] if best is not None else start


class EnergyReceptivity:
    """The outbox's receptivity provider, backed by the energy model."""

    def __init__(self, model: EnergyModel) -> None:
        self.model = model

    def not_before(self, member: Member, priority: Priority, now: datetime) -> datetime:
        member = self.model.store.get_member(member.id)
        if not any(member.tracks(toggle) for toggle in SOURCE_INPUT.values()):
            return now  # no read on them, so no reason to hold anything back
        threshold = STRONG if priority is Priority.LOW else RECEPTIVE
        return next_window(self.model, member, now, threshold=threshold)
