"""The wall's alerts (WA1): one big countdown when someone needs to be somewhere soon.

The Themi Wall Alerts Plan. The server decides which alerts there are and the state each is
in; the page only ticks the seconds between polls (from the part's `data-now`) and plays the
sound a state names.

- Leaving (from K4's heads-ups, `TravelHeadsUps.leavings`): getting ready from ready-from,
  almost in the last five minutes, time to go from leave-by for two minutes, then running
  behind until the event starts. The countdown runs to leave-by, not to the event. Running
  behind says when leaving now gets them there, never minutes late, and plays nothing.
- Kitchen (WA3): the soonest cook timer, and one that's up until someone taps Got it.

At most two show: a kitchen timer that's up, then leaving (the sooner leave-by; the next
waits), then a running timer. Taps (`answer`) are kept per alert in `wall_alert_answers`,
so every frame and a reload agree.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from themi import clock
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.storage.db import Database
    from themi_google.travel import Leaving

ALMOST = timedelta(minutes=5)  # the last five minutes before leave-by
GO = timedelta(minutes=2)  # "Time to go" stays this long after leave-by
SHOWN = 2
ENDS = ("off", "not_going", "got_it")  # answers that take an alert off the wall
QUIET = "quiet"  # keeps the card, without its sounds
ANSWERS = (*ENDS, QUIET)

Kind = Literal["leave", "kitchen"]


@dataclass(frozen=True)
class Button:
    answer: str
    label: str
    main: bool = False


@dataclass(frozen=True)
class WallAlert:
    """One card. `numerals` is what the big line says now; with `counts` ("down" or "up")
    the page ticks it from `ends_at`. `bar` is how far along, 0 to 100, or None."""

    key: str
    kind: Kind
    state: str  # leave: ready, almost, go, behind; kitchen: running, up
    label: str  # "Time to get ready"
    title: str  # "Dentist at 3:00"
    numerals: str  # "12:40", or "Time to go"
    sub: str  # "until we leave at 2:25"
    detail: str  # "Erin · 35 min drive with traffic"
    ends_at: datetime
    rank: int
    tone: str = ""  # the person's colour class, for the dot
    counts: str = ""  # "down", "up" or ""
    bar: int | None = None
    bar_from: str = ""
    bar_to: str = ""
    sound: str = ""  # the trill this state plays once (WA4), or ""
    silent: bool = False  # Quiet was tapped
    next_line: str = ""  # kitchen: "Then: Noodles, step 5"
    next_at: datetime | None = None
    icon: str = ""  # kitchen: "pot" for a cook session's timer, "clock" for one from chat
    buttons: tuple[Button, ...] = ()

    @property
    def ends_iso(self) -> str:
        return to_utc_iso(self.ends_at)

    @property
    def next_iso(self) -> str:
        return to_utc_iso(self.next_at) if self.next_at else ""


def short_time(moment: datetime) -> str:
    """ "2:25", "3:00" (local; the card's words leave out am and pm, as the wall's clock)."""
    return f"{moment.hour % 12 or 12}:{moment.minute:02d}"


def countdown(seconds: float) -> str:
    """ "12:40", "1:05:00"; never below "0:00"."""
    whole = max(0, int(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def drive_words(minutes: int, traffic: bool) -> str:
    if minutes >= 60:
        hours, rest = divmod(minutes, 60)
        said = f"{hours} hr {rest} min" if rest else f"{hours} hr"
    else:
        said = f"{minutes} min"
    return f"{said} drive with traffic" if traffic else f"{said} drive, a rough guess"


def leave_state(leaving: Leaving, now: datetime) -> str:
    """ready, almost, go or behind; "" before getting ready starts or once the event has."""
    if now < leaving.ready_from or now >= leaving.starts_at:
        return ""
    if now < leaving.leave_by - ALMOST:
        return "ready"
    if now < leaving.leave_by:
        return "almost"
    if now < leaving.leave_by + GO:
        return "go"
    return "behind"


def leave_alert(leaving: Leaving, now: datetime, tz: ZoneInfo, tone: str) -> WallAlert | None:
    """The leave card for a heads-up, as it stands at `now`, its words in local time."""
    state = leave_state(leaving, now)
    if not state:
        return None
    leave = short_time(leaving.leave_by.astimezone(tz))
    start = short_time(leaving.starts_at.astimezone(tz))
    title = f"{leaving.title} at {start}" if leaving.title else f"Leaving at {leave}"
    drive = drive_words(leaving.drive_minutes, leaving.traffic)
    left = (leaving.leave_by - now).total_seconds()
    buttons = (Button("off", "We're off", main=True), Button(QUIET, "Quiet"))
    card = WallAlert(
        key=f"leave:{leaving.key}", kind="leave", state=state, label="", title=title,
        numerals="", sub="", detail=f"{' and '.join(leaving.names)} · {drive}",
        ends_at=leaving.leave_by, rank=1, tone=tone,
        buttons=buttons,
    )  # fmt: skip
    if state == "ready":
        span = (leaving.leave_by - leaving.ready_from).total_seconds()
        done = (now - leaving.ready_from).total_seconds()
        return replace(
            card, label="Time to get ready", numerals=countdown(left), counts="down",
            sub=f"until we leave at {leave}", bar=round(100 * done / span) if span > 0 else 0,
            bar_from=f"Ready from {short_time(leaving.ready_from.astimezone(tz))}",
            bar_to=f"Out the door {leave}", sound="ready",
        )  # fmt: skip
    if state == "almost":
        return replace(
            card, label="Almost time to go", numerals=countdown(left), counts="down",
            sub=f"out the door at {leave}",
            bar=round(100 * (1 - left / ALMOST.total_seconds())), sound="five",
        )  # fmt: skip
    if state == "go":
        return replace(
            card, label="Time to go", numerals="Time to go", sound="go",
            buttons=(Button("off", "We're off", main=True),),
        )  # fmt: skip
    there = now + timedelta(minutes=leaving.drive_minutes)  # behind: no sound, no minutes late
    return replace(
        card, label=title, title="Leaving now", numerals=short_time(there.astimezone(tz)),
        sub=f"gets you there around then, {drive}",
        buttons=(Button("off", "We're off", main=True), Button("not_going", "Not going")),
    )  # fmt: skip


def ranked(alerts: list[WallAlert]) -> list[WallAlert]:
    """At most two: a timer that's up, then leaving (only the soonest), then a running timer."""
    leave = sorted((a for a in alerts if a.kind == "leave"), key=lambda a: a.ends_at)[:1]
    rest = [a for a in alerts if a.kind != "leave"]
    return sorted([*leave, *rest], key=lambda a: (a.rank, a.ends_at))[:SHOWN]


class AlertAnswers:
    """What's been tapped on each alert (WA2): off, not going, got it, or quiet."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def answer(self, key: str, answer: str) -> None:
        if answer not in ANSWERS:
            raise ValueError(f"not an answer: {answer!r}")
        self.db.execute(
            "INSERT OR REPLACE INTO wall_alert_answers (alert_key, answer, at) VALUES (?, ?, ?)",
            (key, answer, to_utc_iso(clock.now())),
        )

    def given(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for row in self.db.query("SELECT alert_key, answer FROM wall_alert_answers"):
            out.setdefault(row["alert_key"], set()).add(row["answer"])
        return out

    def apply(self, alerts: list[WallAlert]) -> list[WallAlert]:
        given = self.given()
        kept = []
        for alert in alerts:
            said = given.get(alert.key, set())
            if said & set(ENDS):
                continue
            kept.append(replace(alert, silent=True) if QUIET in said else alert)
        return kept


def answer_alert(services: Services, key: str, answer: str) -> None:
    """A tap on a card, kept so every frame agrees (WA2)."""
    AlertAnswers(services.store.db).answer(key, answer)
