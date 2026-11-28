"""The wall's alerts (WA1): one big countdown when someone needs to be somewhere soon.

The Themi Wall Alerts Plan. The server decides which alerts there are and the state each is
in; the page only ticks the seconds between polls (from the part's `data-now`) and plays the
sound a state names.

- Leaving (from K4's heads-ups, `TravelHeadsUps.leavings`): getting ready from ready-from,
  almost in the last five minutes, time to go from leave-by for two minutes, then running
  behind until the event starts. The countdown runs to leave-by, not to the event. Running
  behind says when leaving now gets them there, never minutes late, and plays nothing.
- Kitchen (WA3): the soonest cook timer, and one that's up until someone taps Got it (which
  clears it on the cook screen too). A timer with no cook session (set from chat) shows a
  clock, not the pot, and its own label.

At most two show: a kitchen timer that's up, then leaving (the sooner leave-by; the next
waits), then a running timer. Taps (`answer`) are kept per alert in `wall_alert_answers`,
so every frame and a reload agree.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from themi import clock
from themi.core import keys
from themi.localtime import to_utc_iso
from themi_home.cooking_timers import _short

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.storage.db import Database
    from themi_google.travel import Leaving

ALMOST = timedelta(minutes=5)  # the last five minutes before leave-by
GO = timedelta(minutes=2)  # "Time to go" stays this long after leave-by
AGAIN = timedelta(minutes=2)  # WA4: a timer that's up and not tapped trills once more then
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
    bar: int | None = None  # bug #287 (WA5): the share of the time left, emptying
    bar_since: datetime | None = None  # when the bar was full; the page empties it to ends_at
    bar_from: str = ""
    bar_to: str = ""
    sound: str = ""  # the trill this state plays once (WA4), or ""
    sound_key: str = ""  # what "once" is counted by on the page: the state, or "up-again"
    silent: bool = False  # Quiet was tapped
    chirp: bool = False  # WA4: a tap on We're off or Got it chirps (its sounds are on)
    next_line: str = ""  # kitchen: "Then: Noodles, step 5"
    next_at: datetime | None = None
    icon: str = ""  # kitchen: "pot" for a cook session's timer, "clock" for one from chat
    up_since: datetime | None = None  # kitchen: when the timer went off, counted up from
    up_for: str = ""  # "+0:42"
    buttons: tuple[Button, ...] = ()

    @property
    def ends_iso(self) -> str:
        return to_utc_iso(self.ends_at)

    @property
    def bar_since_iso(self) -> str:
        return to_utc_iso(self.bar_since) if self.bar_since else ""

    @property
    def up_iso(self) -> str:
        return to_utc_iso(self.up_since) if self.up_since else ""

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


def left_of(seconds: float, span: timedelta) -> int:
    """The bar: how much of `span` is left, 0 to 100 (bug #287: it empties, never fills)."""
    whole = span.total_seconds()
    return max(0, min(100, round(100 * seconds / whole))) if whole > 0 else 0


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
        return replace(
            card, label="Time to get ready", numerals=countdown(left), counts="down",
            sub=f"until we leave at {leave}",
            bar=left_of(left, leaving.leave_by - leaving.ready_from), bar_since=leaving.ready_from,
            bar_from=f"Ready from {short_time(leaving.ready_from.astimezone(tz))}",
            bar_to=f"Out the door {leave}", sound="ready",
        )  # fmt: skip
    if state == "almost":
        return replace(
            card, label="Almost time to go", numerals=countdown(left), counts="down",
            sub=f"out the door at {leave}",
            bar=left_of(left, ALMOST), bar_since=leaving.leave_by - ALMOST, sound="five",
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


def up_words(minutes: float) -> str:
    """ "10 minutes are up", "1 minute is up", "30 seconds are up", "1 hr 30 min is up"."""
    if minutes < 1:
        return f"{round(minutes * 60)} seconds are up"
    if minutes >= 60:
        return f"{_short(minutes)} is up"
    if minutes == 1:
        return "1 minute is up"
    return f"{minutes:g} minutes are up"


def timer_title(row: dict[str, Any]) -> str:
    """ "Pad Thai · Sauce, step 3" for a cook session's timer; one with no session (set from
    chat) by its own label."""
    label = row["label"] or f"Step {row['step']}"
    return f"{row['recipe']} · {label}" if row["session_id"] else (row["label"] or row["recipe"])


def kitchen_alerts(
    rows: list[dict[str, Any]], now: datetime, tz: ZoneInfo, tones: dict[int, str]
) -> list[WallAlert]:
    """WA3: a card for the timer that's gone off longest ago and isn't tapped, and one for
    the soonest still running, each naming the next timer to come."""
    up = [r for r in rows if r["fired_at"]]
    running = [r for r in rows if not r["fired_at"]]
    out: list[WallAlert] = []

    def then(after: list[dict[str, Any]], word: str) -> tuple[str, datetime | None]:
        if not after:
            return "", None
        return f"{word}: {timer_title(after[0])}", datetime.fromisoformat(after[0]["ends_at"])

    if up:
        row = min(up, key=lambda r: r["fired_at"])
        fired = datetime.fromisoformat(row["fired_at"])
        line, at = then(running, "Next")
        minutes = float(row["minutes"])
        out.append(
            WallAlert(
                key=f"timer:{row['id']}",
                kind="kitchen",
                state="up",
                label=timer_title(row),
                title="",
                numerals="Kitchen time" if row["step"] else "Time's up",  # WA6: from chat
                sub=up_words(minutes),
                detail="",
                ends_at=fired,
                rank=0,
                tone=tones.get(row["member_id"], ""),
                sound="kitchen",
                next_line=line,
                next_at=at,
                up_since=fired,
                up_for=f"+{countdown((now - fired).total_seconds())}",
                sound_key="up-again" if now - fired >= AGAIN else "up",
                icon="pot" if row["session_id"] else "clock",
                buttons=(Button("got_it", "Got it", main=True),),
            )
        )
    if running:
        row = running[0]
        ends = datetime.fromisoformat(row["ends_at"])
        total = float(row["minutes"]) * 60
        left = (ends - now).total_seconds()
        line, at = then(running[1:], "Then")
        out.append(
            WallAlert(
                key=f"timer:{row['id']}",
                kind="kitchen",
                state="running",
                label="Back to the kitchen in" if row["step"] else "Timer",  # WA6: from chat
                title=timer_title(row),
                numerals=countdown(left),
                counts="down",
                sub="",
                detail="",
                ends_at=ends,
                rank=2,
                tone=tones.get(row["member_id"], ""),
                bar=left_of(left, timedelta(seconds=total)),
                bar_since=ends - timedelta(seconds=total),
                bar_from=f"of {countdown(total)}",
                bar_to=f"done at {short_time(ends.astimezone(tz))}",
                next_line=line,
                next_at=at,
                icon="pot" if row["session_id"] else "clock",
            )
        )
    return out


def heard(alert: WallAlert, sounds: str) -> WallAlert:
    """WA4: the alert with no sound when the wall's setting (On, Kitchen only, Off) or its
    Quiet says so. Only a kitchen timer that's up plays a second time."""
    if alert.silent or sounds == "Off" or (sounds == "Kitchen only" and alert.kind != "kitchen"):
        return replace(alert, sound="", chirp=False)
    return replace(alert, chirp=True)


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
    """A tap on a card, kept so every frame agrees (WA2). Got it on a timer clears it as a
    tap on the cook screen does (WA3), so the two agree."""
    AlertAnswers(services.store.db).answer(key, answer)
    if answer == "got_it" and key.startswith("timer:"):
        cooking = services.maybe(keys.cooking)
        timer_id = int(key.removeprefix("timer:"))
        row = services.store.db.one(
            "SELECT member_id FROM cooking_timers WHERE id = ?", (timer_id,)
        )
        if cooking is not None and cooking.timers is not None and row is not None:
            cooking.timers.clear(row["member_id"], timer_id)
