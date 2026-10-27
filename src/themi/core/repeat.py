"""Chore schedules in words (F7): "every Tuesday at 6pm", "twice a week".

The model passes a short phrase; this module parses it deterministically into a
`Repeat`, refuses anything it can't read (listing what it can), and reads the
stored schedule back in plain words. That read-back is built here from what was
stored, never from the model's own summary, so a misunderstanding shows at once.

Two kinds of schedule:
- floating: "N times a week", counted from the last time it was done (F6b);
- anchored: fixed dates, as RFC 5545 recurrence rules computed with
  `dateutil.rrule` ("every Tuesday", "every other Monday", "the first Monday of
  each month", "every 3 days"), optionally at a time of day.

Anchored weekly schedules can also have either-day rounds ("Saturday or Sunday": one
round, due Saturday and still fine Sunday), and any anchored one a rest rule ("never
two days in a row"), which the task board keeps when it sets a round's day (F9a).

Occurrences are computed on local wall-clock times and then given the family's
timezone, so "Tuesday at 6 pm" stays 6 pm across daylight-saving changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser
from dateutil import rrule

from themi import clock

Kind = Literal["floating", "daily", "weekly", "monthly"]

EXAMPLES = (
    "Try a phrase like: 'every Tuesday at 6pm', 'every other Monday', 'every Tue and Fri', "
    "'twice a week', 'every 3 days', 'first Monday of the month', 'the 1st of every month'."
)
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_DAY_WORDS = {
    **{name.lower(): i for i, name in enumerate(DAY_NAMES)},
    **{name.lower()[:3]: i for i, name in enumerate(DAY_NAMES)},
    "tues": 1,
    "weds": 2,
    "thur": 3,
    "thurs": 3,
}
_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3}
_ORDINALS |= {"fourth": 4, "4th": 4, "last": -1}
_POSITION_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}
_TIME_WORDS = {
    "in the morning": time(9),
    "mornings": time(9),
    "morning": time(9),
    "in the afternoon": time(14),
    "afternoons": time(14),
    "afternoon": time(14),
    "in the evening": time(18),
    "evenings": time(18),
    "evening": time(18),
    "at night": time(20),
    "nights": time(20),
    "night": time(20),
    "at noon": time(12),
    "noon": time(12),
}
_RRULE_DAYS = (rrule.MO, rrule.TU, rrule.WE, rrule.TH, rrule.FR, rrule.SA, rrule.SU)


class RepeatError(ValueError):
    """A phrase that couldn't be read as a schedule. The message says what would work."""


@dataclass(frozen=True)
class Repeat:
    kind: Kind
    times_per_week: float | None = None  # floating
    every: int = 1  # days, weeks or months between rounds (anchored)
    weekdays: tuple[int, ...] = field(default_factory=tuple)  # 0 is Monday
    month_position: int | None = None  # 1-4, or -1 for the last (with one weekday)
    month_day: int | None = None  # 1-31
    at: time | None = None  # time of day, if any
    start: date | None = None  # where the rhythm starts (anchored)
    until: date | None = None  # the last day it can fall on (a course of medicine, C2a)
    or_days: tuple[int, ...] = field(default_factory=tuple)  # stand-ins for the day before
    rest: bool = False  # never two days in a row
    # Minutes before sunset (F9b; 0 is at sunset). With `at` too, whichever is earlier
    # ("at 2pm, at least an hour before sunset"). The time itself needs the home's place.
    before_sunset: int | None = None

    @property
    def anchored(self) -> bool:
        return self.kind != "floating"

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "times_per_week": self.times_per_week,
            "every": self.every,
            "weekdays": list(self.weekdays),
            "month_position": self.month_position,
            "month_day": self.month_day,
            "at": self.at.strftime("%H:%M") if self.at else None,
            "start": self.start.isoformat() if self.start else None,
            "until": self.until.isoformat() if self.until else None,
            "or_days": list(self.or_days),
            "rest": self.rest,
            "before_sunset": self.before_sunset,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Repeat:
        return cls(
            kind=data["kind"],
            times_per_week=data.get("times_per_week"),
            every=int(data.get("every") or 1),
            weekdays=tuple(data.get("weekdays") or ()),
            month_position=data.get("month_position"),
            month_day=data.get("month_day"),
            at=time.fromisoformat(data["at"]) if data.get("at") else None,
            start=date.fromisoformat(data["start"]) if data.get("start") else None,
            until=date.fromisoformat(data["until"]) if data.get("until") else None,
            or_days=tuple(data.get("or_days") or ()),
            rest=bool(data.get("rest")),
            before_sunset=data.get("before_sunset"),
        )


# ----- parsing ------------------------------------------------------------------------


def _take_time(text: str) -> tuple[str, time | None]:
    """Pull a time of day out of the phrase: "at 6pm", "7:30 am", "18:00", "in the evening"."""
    m = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if not 1 <= hour <= 12 or minute > 59:
            raise RepeatError(f"'{m.group(0).strip()}' isn't a time of day. {EXAMPLES}")
        hour = hour % 12 + (12 if m.group(3) == "pm" else 0)
        return (text[: m.start()] + text[m.end() :]).strip(), time(hour, minute)
    m = re.search(r"\b(?:at\s+)(\d{1,2})(?::(\d{2}))?\b|\b(\d{1,2}):(\d{2})\b", text)
    if m:
        hour = int(m.group(1) or m.group(3))
        minute = int(m.group(2) or m.group(4) or 0)
        if m.group(1) and not m.group(2) and 1 <= hour <= 7:
            hour += 12  # "at 6" for a chore means the evening, not 6 in the morning
        if hour > 23 or minute > 59:
            raise RepeatError(f"'{m.group(0).strip()}' isn't a time of day. {EXAMPLES}")
        return (text[: m.start()] + text[m.end() :]).strip(), time(hour, minute)
    for words, at in _TIME_WORDS.items():
        m = re.search(rf"\b{words}\b", text)
        if m:
            return (text[: m.start()] + text[m.end() :]).strip(), at
    return text, None


def day_number(word: str) -> int | None:
    """A day's name ("tuesday", "tue", "tuesdays") as a number, 0 for Monday."""
    return _DAY_WORDS[word] if word in _DAY_WORDS else _DAY_WORDS.get(word.rstrip("s"))


def _days(text: str) -> tuple[int, ...]:
    found = []
    for word in re.findall(r"[a-z]+", text):
        day = day_number(word)
        if day is not None and day not in found:
            found.append(day)
    return tuple(sorted(found))


def _take_or_days(text: str) -> tuple[str, tuple[int, ...]]:
    """Pull either-day rounds out: "saturday or sunday" leaves "saturday", and Sunday as
    its stand-in. Only a day and the one after it."""
    found = []
    for m in reversed(list(re.finditer(r"\b([a-z]+)\s+or\s+([a-z]+)\b", text))):
        first, second = day_number(m.group(1)), day_number(m.group(2))
        if first is None or second is None:
            continue
        if second != (first + 1) % 7:
            raise RepeatError(
                f"'{m.group(0)}' needs to be a day and the one after it ('Saturday or "
                f"Sunday'). {EXAMPLES}"
            )
        found.append(second)
        text = text[: m.start()] + m.group(1) + text[m.end() :]
    return text, tuple(sorted(found))


_REST = re.compile(
    r"[,;]?\s*(?:but\s+|and\s+)?(?:never|no|not)\s+(?:two|2)\s+days\s+in\s+a\s+row",
    re.IGNORECASE,
)


_SUNSET = re.compile(
    r"[,;]?\s*(?:at\s+least\s+)?(?:(?:(an?|one|\d+)\s*(hours?|hrs?|minutes?|mins?)\s+)"
    r"before\s+sunset|at\s+sunset)",
    re.IGNORECASE,
)


def _take_sunset(phrase: str) -> tuple[str, int | None]:
    """Pull "an hour before sunset" (or "at sunset") off the phrase: minutes before it."""
    m = _SUNSET.search(phrase)
    if not m:
        return phrase, None
    if m.group(1) is None:
        minutes = 0  # at sunset
    else:
        count = 1 if m.group(1).lower() in ("a", "an", "one") else int(m.group(1))
        minutes = count * 60 if m.group(2).lower().startswith("h") else count
    if minutes > 12 * 60:
        raise RepeatError(f"That's more than half a day before sunset. {EXAMPLES}")
    return phrase[: m.start()] + phrase[m.end() :], minutes


def _take_rest(phrase: str) -> tuple[str, bool]:
    """Pull "never two days in a row" off the phrase."""
    m = _REST.search(phrase)
    if not m:
        return phrase, False
    return phrase[: m.start()] + phrase[m.end() :], True


def _take_until(phrase: str, today: date) -> tuple[str, date | None]:
    """Pull an end date off the phrase: "... until 30 Oct", "... until 2026-11-10"."""
    m = re.search(r"\s+(?:until|till|through)\s+(.+)$", phrase, re.IGNORECASE)
    if not m:
        return phrase, None
    default = datetime(today.year, today.month, today.day)  # noqa: DTZ001
    try:
        until = dateutil_parser.parse(m.group(1), default=default).date()
    except (ValueError, OverflowError) as exc:
        raise RepeatError(f"'{m.group(1)}' isn't a date. {EXAMPLES}") from exc
    if until < today:
        raise RepeatError(f"{until:%a %d %b} has already gone by. {EXAMPLES}")
    return phrase[: m.start()], until


def parse(phrase: str, today: date) -> Repeat:
    """Read a schedule phrase. Raises RepeatError, with examples, if it isn't clear."""
    phrase, rest = _take_rest(phrase)
    phrase, before_sunset = _take_sunset(phrase)
    rep = _parse(*_take_until(phrase, today), today)
    if rest and not rep.anchored:
        raise RepeatError(
            f"'Never two days in a row' needs fixed days ('every Tue, Thu and Sat, never two "
            f"days in a row'). {EXAMPLES}"
        )
    if before_sunset is not None and not rep.anchored:
        raise RepeatError(f"A time by sunset needs fixed days ('every Tuesday'). {EXAMPLES}")
    return replace(rep, rest=rest, before_sunset=before_sunset)


def _parse(phrase: str, until: date | None, today: date) -> Repeat:
    rep = _parse_rhythm(phrase, today)
    if until is None:
        return rep
    if not rep.anchored:
        raise RepeatError(f"An end date needs fixed days ('every 2 days until 30 Oct'). {EXAMPLES}")
    return replace(rep, until=until)


def _parse_rhythm(phrase: str, today: date) -> Repeat:
    text = " ".join(re.sub(r"[^a-z0-9: ]", " ", phrase.lower().replace("&", " and ")).split())
    if not text:
        raise RepeatError(f"There's no schedule there. {EXAMPLES}")
    text, at = _take_time(text)
    text, or_days = _take_or_days(" ".join(text.split()))
    rep = _parse_days(text, at, phrase, today)
    if not or_days:
        return rep
    if rep.kind != "weekly" or set(or_days) & set(rep.weekdays):
        raise RepeatError(f"'Or' works for weekly days ('every Saturday or Sunday'). {EXAMPLES}")
    return replace(rep, or_days=or_days)


def _parse_days(text: str, at: time | None, phrase: str, today: date) -> Repeat:

    m = re.fullmatch(r"(once|twice|\d+(?:\.\d+)?)\s*(?:times?|x)?\s*(?:a|per|each)\s+week", text)
    if m:
        word = m.group(1)
        times = 1.0 if word == "once" else 2.0 if word == "twice" else float(word)
        if not 0 < times <= 14:
            raise RepeatError(f"'{phrase}' isn't between once and 14 times a week. {EXAMPLES}")
        return Repeat("floating", times_per_week=times)

    if re.fullmatch(r"(?:every\s+day|daily|each\s+day|every\s+single\s+day)", text):
        return Repeat("daily", at=at, start=today)
    if text == "every other day":
        return Repeat("daily", every=2, at=at, start=today)
    m = re.fullmatch(r"every\s+(\d+)\s+days?", text)
    if m:
        return Repeat("daily", every=_positive(m.group(1), phrase), at=at, start=today)

    m = re.fullmatch(
        r"(?:monthly\s+on\s+the\s+|on\s+the\s+|the\s+)?(first|1st|second|2nd|third|3rd|fourth|"
        r"4th|last)\s+([a-z]+)\s+(?:of\s+)?(?:the|each|every)?\s*month|monthly\s+on\s+the\s+"
        r"(first|1st|second|2nd|third|3rd|fourth|4th|last)\s+([a-z]+)",
        text,
    )
    if m:
        ordinal, day_word = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        days = _days(day_word)
        if len(days) == 1:
            return Repeat(
                "monthly", weekdays=days, month_position=_ORDINALS[ordinal], at=at, start=today
            )
    m = re.fullmatch(
        r"(?:monthly\s+on\s+the\s+|on\s+the\s+|the\s+)?(\d{1,2})(?:st|nd|rd|th)?"
        r"(?:\s+of\s+(?:the|each|every)\s+month|\s+monthly)?",
        text,
    )
    if m and ("month" in text):
        day = int(m.group(1))
        if not 1 <= day <= 31:
            raise RepeatError(f"'{phrase}' isn't a day of the month. {EXAMPLES}")
        return Repeat("monthly", month_day=day, at=at, start=today)

    days = _days(text)
    if days:
        rest = text
        for word in re.findall(r"[a-z]+", text):
            if word in _DAY_WORDS or word.rstrip("s") in _DAY_WORDS:
                rest = re.sub(rf"\b{word}\b", " ", rest)
        rest = " ".join(re.sub(r"\b(?:and|on|weekly)\b", " ", rest).split())
        every = None
        if rest in ("every", "", "each"):
            every = 1
        elif rest in ("every other", "every second", "fortnightly"):
            every = 2
        else:
            m = re.fullmatch(r"every\s+(\d+)\s+weeks?", rest)
            if m:
                every = _positive(m.group(1), phrase)
        if every is not None:
            return Repeat("weekly", every=every, weekdays=days, at=at, start=today)

    raise RepeatError(f"I couldn't read '{phrase}' as a schedule. {EXAMPLES}")


def _positive(number: str, phrase: str) -> int:
    value = int(number)
    if not 1 <= value <= 365:
        raise RepeatError(f"'{phrase}' needs a number from 1 to 365. {EXAMPLES}")
    return value


# ----- reading back ---------------------------------------------------------------------


def _time_words(at: time) -> str:
    hour = at.hour % 12 or 12
    suffix = "am" if at.hour < 12 else "pm"
    return f"{hour}:{at.minute:02d} {suffix}" if at.minute else f"{hour} {suffix}"


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + f" and {words[-1]}"


def _ordinal_day(day: int) -> str:
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def read_back(rep: Repeat) -> str:
    """The schedule in plain words, from what's stored."""
    if rep.kind == "floating":
        times = rep.times_per_week or 0
        often = {1: "Once", 2: "Twice"}.get(int(times)) if times == int(times) else None
        return f"{often or f'{times:g} times'} a week, counted from the last time it was done"
    if rep.kind == "daily":
        text = {1: "Every day", 2: "Every other day"}.get(rep.every, f"Every {rep.every} days")
    elif rep.kind == "weekly":
        days = _and([_day_words(rep, d) for d in rep.weekdays])
        if rep.every == 1:
            text = f"Every {days}"
        elif rep.every == 2 and len(rep.weekdays) == 1:
            text = f"Every other {days}"
        else:
            text = f"Every {rep.every} weeks on {days}"
    elif rep.month_position is not None:
        day = DAY_NAMES[rep.weekdays[0]]
        text = f"The {_POSITION_WORDS[rep.month_position]} {day} of each month"
    else:
        text = f"The {_ordinal_day(rep.month_day or 1)} of each month"
    text = f"{text} at {_time_words(rep.at)}" if rep.at else text
    if rep.before_sunset is not None:
        sun = sunset_words(rep.before_sunset)
        text = f"{text}, at least {sun}" if rep.at and rep.before_sunset else f"{text}, {sun}"
    text = f"{text}, never two days in a row" if rep.rest else text
    return f"{text}, until {rep.until:%a %d %b}" if rep.until else text


def sunset_words(minutes: int) -> str:
    """60: "an hour before sunset"; 90: "1 hour 30 minutes before sunset"; 0: "at sunset"."""
    if minutes == 0:
        return "at sunset"
    hours, rest = divmod(minutes, 60)
    parts = (["an hour"] if hours == 1 else [f"{hours} hours"] if hours else []) + (
        [f"{rest} minutes"] if rest else []
    )
    return " ".join(parts) + " before sunset"


def _day_words(rep: Repeat, day: int) -> str:
    following = (day + 1) % 7
    or_day = f" or {DAY_NAMES[following]}" if following in rep.or_days else ""
    return DAY_NAMES[day] + or_day


def round_end(rep: Repeat, due: date) -> date:
    """The last day a round due on `due` is still on time: the day after, for an either-day
    round ("Saturday or Sunday"), else the day itself."""
    if due.weekday() in rep.weekdays and (due.weekday() + 1) % 7 in rep.or_days:
        return due + timedelta(days=1)
    return due


# ----- occurrences ----------------------------------------------------------------------


def _rule(rep: Repeat) -> rrule.rrule:
    start = rep.start or clock.now().date()  # only hand-built Repeats lack a start
    at = rep.at or time(0)
    # Naive on purpose: wall-clock time, given the timezone after (see next_occurrences).
    dtstart = datetime(start.year, start.month, start.day, at.hour, at.minute)  # noqa: DTZ001
    until = (
        datetime(rep.until.year, rep.until.month, rep.until.day, 23, 59)  # noqa: DTZ001
        if rep.until
        else None
    )
    if rep.kind == "daily":
        return rrule.rrule(rrule.DAILY, interval=rep.every, dtstart=dtstart, until=until)
    if rep.kind == "weekly":
        days = [_RRULE_DAYS[d] for d in rep.weekdays]
        return rrule.rrule(
            rrule.WEEKLY, interval=rep.every, byweekday=days, dtstart=dtstart, until=until
        )
    if rep.month_position is not None:
        day = _RRULE_DAYS[rep.weekdays[0]](rep.month_position)
        return rrule.rrule(
            rrule.MONTHLY, interval=rep.every, byweekday=day, dtstart=dtstart, until=until
        )
    return rrule.rrule(
        rrule.MONTHLY, interval=rep.every, bymonthday=rep.month_day, dtstart=dtstart, until=until
    )


def previous_occurrence(rep: Repeat, before: datetime, tz: ZoneInfo) -> datetime | None:
    """The last occurrence strictly before `before`, or None (or for floating schedules)."""
    if not rep.anchored:
        return None
    found = _rule(rep).before(before.astimezone(tz).replace(tzinfo=None), inc=False)
    return found.replace(tzinfo=tz) if found else None


def next_occurrences(rep: Repeat, after: datetime, tz: ZoneInfo, count: int = 1) -> list[datetime]:
    """The next `count` occurrences strictly after `after`, in the family's timezone.
    Floating schedules have no fixed dates, so they return nothing."""
    if not rep.anchored:
        return []
    rule = _rule(rep)
    cursor = after.astimezone(tz).replace(tzinfo=None)
    found = []
    for _ in range(count):
        nxt = rule.after(cursor, inc=False)
        if nxt is None:
            break
        found.append(nxt.replace(tzinfo=tz))
        cursor = nxt
    return found
