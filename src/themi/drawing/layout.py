"""Where things go on a day's timeline (DC2; the plan's "What the family sees").

Pure: times in, pixels out. The day card (DC3) and the week ahead (DC6) draw from this.

- The window runs from the morning message's time (or the first event, if that's earlier)
  to 9 pm, each end on the hour, and grows to take in an evening event: nothing on the
  calendar is left off the picture.
- Events that overlap sit side by side: each cluster of overlapping events is split into
  as many columns as it needs at its busiest, and each event takes the first free column.
- A block too short to hold a line of words (`LABEL_MIN`) is marked `beside`: the card
  writes its title next to it, smaller.
- All-day events go in a strip above the hours, up to `ALL_DAY_ROWS` rows; the rest are
  counted ("+2 more").
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta

DAY_ENDS = time(21)  # the waking day's end, as the weather line's (WX2)
LABEL_MIN = 22.0  # px: a block shorter than this has its title beside it
BLOCK_MIN = 6.0  # px: the shortest block drawn (a 5-minute event is still seen)
GAP = 4.0  # px between columns
ALL_DAY_ROWS = 2


@dataclass(frozen=True)
class Span:
    """Something with a time: an event, a travel lead-in, a task block."""

    key: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Placed:
    key: str
    x: float
    y: float
    width: float
    height: float
    column: int
    columns: int
    beside: bool  # too short for its title inside
    clipped_top: bool = False  # starts before the window
    clipped_bottom: bool = False  # runs past it


@dataclass(frozen=True)
class Tick:
    at: datetime
    y: float
    label: str


@dataclass(frozen=True)
class Timeline:
    start: datetime
    end: datetime
    top: float
    height: float

    @property
    def bottom(self) -> float:
        return self.top + self.height

    def y(self, at: datetime) -> float:
        """The y of a moment, held inside the timeline."""
        total = (self.end - self.start).total_seconds()
        part = (at - self.start).total_seconds() / total
        return self.top + min(max(part, 0.0), 1.0) * self.height

    def ticks(self) -> list[Tick]:
        """An hour line every hour, or every two when the day is long: labelled "8 am",
        "noon", "2 pm"."""
        hours = int((self.end - self.start).total_seconds() // 3600)
        step = 1 if hours <= 8 else 2
        out = []
        at = self.start
        while at <= self.end:
            out.append(Tick(at, self.y(at), hour_label(at)))
            at += timedelta(hours=step)
        return out


def hour_label(at: datetime) -> str:
    if at.hour == 12 and at.minute == 0:
        return "noon"
    if at.hour == 0 and at.minute == 0:
        return "midnight"
    hour = at.hour % 12 or 12
    clock = f"{hour}" if at.minute == 0 else f"{hour}:{at.minute:02d}"
    return f"{clock} {'am' if at.hour < 12 else 'pm'}"


def _floor_hour(at: datetime) -> datetime:
    return at.replace(minute=0, second=0, microsecond=0)


def _ceil_hour(at: datetime) -> datetime:
    floor = _floor_hour(at)
    return floor if floor == at else floor + timedelta(hours=1)


def window(from_: datetime, spans: Sequence[Span]) -> tuple[datetime, datetime]:
    """The day's window: from `from_` (the morning message's time) or the first event, to
    9 pm or the last event's end, on the hour, inside the day."""
    midnight = from_.replace(hour=0, minute=0, second=0, microsecond=0)
    next_midnight = midnight + timedelta(days=1)
    day_end = midnight.replace(hour=DAY_ENDS.hour)
    starts = [s.start for s in spans if s.start < next_midnight and s.end > midnight]
    ends = [s.end for s in spans if s.start < next_midnight and s.end > midnight]
    start = _floor_hour(max(midnight, min([from_, *starts])))
    end = min(next_midnight, _ceil_hour(max([day_end, *ends])))
    if end <= start:  # a morning time after 9 pm: an hour, at least
        end = min(next_midnight, start + timedelta(hours=1))
    return start, end


def columns(spans: Sequence[Span]) -> dict[str, tuple[int, int]]:
    """Each span's column and how many columns its cluster of overlapping spans has.
    Spans that only touch (one ends as the next begins) don't overlap."""
    order = sorted(spans, key=lambda s: (s.start, -(s.end - s.start).total_seconds(), s.key))
    out: dict[str, tuple[int, int]] = {}
    cluster: list[tuple[Span, int]] = []
    cluster_end: datetime | None = None
    ends: list[datetime] = []  # per column, when it's free again

    def close() -> None:
        width = max((c for _, c in cluster), default=-1) + 1
        for span, column in cluster:
            out[span.key] = (column, width)

    for span in order:
        if cluster_end is not None and span.start >= cluster_end:
            close()
            cluster, ends = [], []
        free = next((i for i, end in enumerate(ends) if end <= span.start), None)
        if free is None:
            ends.append(span.end)
            free = len(ends) - 1
        else:
            ends[free] = span.end
        cluster.append((span, free))
        cluster_end = span.end if cluster_end is None else max(cluster_end, span.end)
    close()
    return out


def place(spans: Sequence[Span], timeline: Timeline, left: float, width: float) -> list[Placed]:
    """Each span as a block on the timeline, in `left` to `left + width`. Spans wholly
    outside the window aren't placed."""
    shown = [s for s in spans if s.end > timeline.start and s.start < timeline.end]
    cols = columns(shown)
    out = []
    for span in shown:
        column, count = cols[span.key]
        col_width = (width - GAP * (count - 1)) / count
        y0, y1 = timeline.y(span.start), timeline.y(span.end)
        height = max(y1 - y0, BLOCK_MIN)
        y0 = min(y0, timeline.bottom - height)
        out.append(
            Placed(
                key=span.key,
                x=left + column * (col_width + GAP),
                y=y0,
                width=col_width,
                height=height,
                column=column,
                columns=count,
                beside=y1 - timeline.y(span.start) < LABEL_MIN,
                clipped_top=span.start < timeline.start,
                clipped_bottom=span.end > timeline.end,
            )
        )
    return sorted(out, key=lambda p: (p.y, p.x))


def all_day_rows(keys: Sequence[str], rows: int = ALL_DAY_ROWS) -> tuple[list[str], int]:
    """The all-day events shown (one per row), and how many more there are."""
    if len(keys) <= rows:
        return list(keys), 0
    return list(keys[: rows - 1]), len(keys) - (rows - 1)
