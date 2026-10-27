"""Plans that step up week by week (F9c): "1.3 miles, then 1.5, then up 0.25 a week, on
Tuesdays" (Erin's runs).

Like schedules (`themi.core.repeat`), the model passes a short phrase; this module parses it
deterministically, refuses what it can't read (with an example), and reads the stored plan
back in plain words, so a misunderstanding shows at once. A task's nudge then says the
week's amount: "Check-in: Go for a run (1.3 miles this week)".

A plan's week runs from its step day to the day before the next one: with steps on
Tuesdays, Monday still has last week's amount.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from dateutil import parser as dateutil_parser

from themi.core.repeat import DAY_NAMES, day_number

EXAMPLE = "Try a plan like: '1.3 miles, then 1.5, then up 0.25 a week, on Tuesdays'."
_NUMBER = r"(\d+(?:\.\d+)?)"


class ProgressionError(ValueError):
    """A plan that couldn't be read. The message has an example that works."""


@dataclass(frozen=True)
class Progression:
    unit: str  # "miles", "km", "minutes"
    amounts: tuple[float, ...]  # the first weeks, as said
    step: float  # added each week after them (0: stays at the last)
    weekday: int  # the day it steps up, 0 is Monday
    start: date  # the first week's step day
    up_to: float | None = None  # where it stops going up

    def amount_on(self, day: date) -> float | None:
        """That day's week's amount, or None before the plan starts."""
        if day < self.start:
            return None
        weeks = (day - self.start).days // 7
        if weeks < len(self.amounts):
            amount = self.amounts[weeks]
        else:
            amount = self.amounts[-1] + self.step * (weeks - len(self.amounts) + 1)
        if self.up_to is not None:
            amount = min(amount, self.up_to)
        return round(amount, 3)

    def words_on(self, day: date) -> str | None:
        """For a nudge: "1.5 miles this week"."""
        amount = self.amount_on(day)
        return None if amount is None else f"{_number(amount)} {self.unit} this week"

    def to_json(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "amounts": list(self.amounts),
            "step": self.step,
            "weekday": self.weekday,
            "start": self.start.isoformat(),
            "up_to": self.up_to,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Progression:
        return cls(
            unit=data["unit"],
            amounts=tuple(data["amounts"]),
            step=float(data.get("step") or 0),
            weekday=int(data["weekday"]),
            start=date.fromisoformat(data["start"]),
            up_to=data.get("up_to"),
        )


def parse_plan(phrase: str, today: date) -> Progression:
    """Read a plan phrase. Raises ProgressionError, with an example, if it isn't clear."""
    text = " ".join(phrase.lower().replace(",", " , ").split())
    text, start = _take(text, r"\b(?:starting|from)\s+(?:on\s+)?(.+?)(?=\s*,|\s+on\s|$)")
    text, day_word = _take(text, r"\b(?:on|every)\s+([a-z]+)")
    text, up_to = _take(text, rf"\bup\s+to\s+{_NUMBER}(?:\s*[a-z]+)?")
    if re.search(r"\bdown\b", text):
        raise ProgressionError(f"Plans here only go up or stay put. {EXAMPLE}")
    text, step = _take(
        text, rf"\b(?:then\s+)?up\s+(?:by\s+)?{_NUMBER}(?:\s*[a-z]+)?\s+(?:a|per|each)\s+week"
    )
    m = re.fullmatch(
        rf"{_NUMBER}\s*([a-z]+)((?:\s*,?\s*(?:then\s+)?{_NUMBER}(?:\s*[a-z]+)?)*)", _tidy(text)
    )
    if not m:
        raise ProgressionError(f"I couldn't read '{phrase}' as a plan. {EXAMPLE}")
    amounts = (float(m.group(1)), *(float(n) for n in re.findall(_NUMBER, m.group(3))))
    if not all(a > 0 for a in amounts):
        raise ProgressionError(f"A plan's amounts are more than zero. {EXAMPLE}")
    weekday = day_number(day_word) if day_word else None
    if day_word and weekday is None:
        raise ProgressionError(f"'{day_word}' isn't a day of the week. {EXAMPLE}")
    first = _start(start, today) if start else today
    if weekday is None:
        weekday = first.weekday()
    first += timedelta(days=(weekday - first.weekday()) % 7)  # its step day, on or after
    return Progression(
        unit=m.group(2),
        amounts=amounts,
        step=float(step) if step else 0.0,
        weekday=weekday,
        start=first,
        up_to=float(up_to) if up_to else None,
    )


def _take(text: str, pattern: str) -> tuple[str, str | None]:
    m = re.search(pattern, text)
    if not m:
        return text, None
    return text[: m.start()] + " " + text[m.end() :], m.group(1)


def _tidy(text: str) -> str:
    """Drop the commas and "then"s left at the ends once the other parts are taken out."""
    text = " ".join(text.split())
    return re.sub(r"^(?:[,\s]|then\b)+|(?:[,\s]|\bthen)+$", "", text)


def _start(words: str, today: date) -> date:
    default = datetime(today.year, today.month, today.day)  # noqa: DTZ001
    try:
        return dateutil_parser.parse(words, default=default).date()
    except (ValueError, OverflowError) as exc:
        raise ProgressionError(f"'{words}' isn't a date. {EXAMPLE}") from exc


def _number(value: float) -> str:
    return f"{value:g}"


def read_back(plan: Progression) -> str:
    """The plan in plain words, from what's stored."""
    text = f"{_number(plan.amounts[0])} {plan.unit} from {plan.start:%a %d %b}"
    text += "".join(f", then {_number(a)}" for a in plan.amounts[1:])
    if plan.step:
        text += f", then up {_number(plan.step)} a week"
    if plan.up_to is not None:
        text += f", up to {_number(plan.up_to)} {plan.unit}"
    if len(plan.amounts) > 1 or plan.step:
        text += f"; it steps up on {DAY_NAMES[plan.weekday]}s"
    return text
