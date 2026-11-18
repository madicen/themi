"""The usage card (UC4; the Themi Usage Plan's "The usage card" and "Where it shows").

One picture for the household's admins: a row for each meter (and each backend or device
of it) used this month, grouped (AI, Devices, Google, Web), with today's bar against the
daily limit and this month's total at the right. A meter with only a monthly limit draws
the month instead, with an even pace to today and where the month is heading. At the
bottom, the AI's requests over the last 30 days.

- Bars: good under 75% of the limit, getting close from 75%, over at 100% or after any
  refusal today. A bar never runs past its track; the words say how far.
- Words come from the meters and the AI page's backend labels, never a person's name or
  key. Counts carry thousands separators; no percentages are printed.
- On request only (`/usage`, `show_usage`), admins only.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from themi.core import keys
from themi.drawing.svg import write_svg
from themi.drawing.text import fit
from themi.standard.day_card import THEMES
from themi.usage import GROUPS, Meter, Totals, UsageBook

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi.core.services import Services

WIDTH = 760
PNG_WIDTH = 1520
PAD = 24
LABEL_W = 172
BAR_X = PAD + LABEL_W + 12
BAR_W = 220
VALUE_X = BAR_X + BAR_W + 14
VALUE_W = 112
ROW_H = 36
GROUP_H = 40
SPARK_H = 64
NEAR = 0.75
CAPTION = "How much Themi used today and this month."
NOT_ADMIN = "That's for the household's admins."
NOTHING = "Nothing used yet this month."


@dataclass(frozen=True)
class UsageRow:
    label: str
    unit: str
    today: float
    month: float
    per_day: float | None = None
    per_month: float | None = None
    refused: int = 0
    estimate: float | None = None
    day_of_month: int = 1
    days_in_month: int = 30

    @property
    def monthly(self) -> bool:
        """Drawn by the month: a monthly limit and no daily one."""
        return self.per_day is None and self.per_month is not None

    @property
    def share(self) -> float | None:
        if self.per_day:
            return self.today / self.per_day
        if self.per_month:
            return self.month / self.per_month
        return None

    @property
    def pace(self) -> float | None:
        """A monthly row: how much of the month's limit an even pace has used by today."""
        return self.day_of_month / self.days_in_month if self.monthly else None

    @property
    def projected(self) -> float | None:
        """A monthly row: the month's total at this rate."""
        if not self.monthly:
            return None
        return self.month / self.day_of_month * self.days_in_month

    @property
    def state(self) -> str:
        share = self.share
        if self.refused or (share is not None and share >= 1):
            return "over"
        if share is not None and share >= NEAR:
            return "near"
        return "good"


@dataclass(frozen=True)
class UsageGroup:
    name: str
    rows: tuple[UsageRow, ...]


@dataclass(frozen=True)
class UsageData:
    day: date
    groups: tuple[UsageGroup, ...]
    ai_days: tuple[int, ...] = ()  # the AI's requests a day, the last 30, today last


def collect(usage: UsageBook, backend_labels: dict[str, str] | None = None) -> UsageData:
    """What the card shows, from the book: the meters used this month, by group."""
    labels = backend_labels or {}
    grouped: dict[str, list[tuple[int, UsageRow]]] = {}
    for meter in usage.meters.values():
        if meter.read is not None:
            continue  # UC later: read meters
        scopes = usage.scopes(meter.key)
        for scope in scopes:
            row = _row(usage, meter, scope, scopes, labels)
            if row.month or row.today or row.refused:
                grouped.setdefault(meter.group, []).append((meter.order, row))
    order = {name: i for i, name in enumerate(GROUPS)}
    groups = tuple(
        UsageGroup(name, tuple(r for _, r in sorted(rows, key=lambda x: (x[0], x[1].label))))
        for name, rows in sorted(grouped.items(), key=lambda g: (order.get(g[0], 99), g[0]))
    )
    ai = [m.key for m in usage.meters.values() if m.group == "AI" and m.key.endswith(".requests")]
    days = [0] * 30
    for key in ai:
        for i, (_, totals) in enumerate(usage.days(key, 30)):
            days[i] += totals.count
    family_day = usage.day("")
    return UsageData(family_day, groups, tuple(days) if any(days) else ())


def _row(
    usage: UsageBook, meter: Meter, scope: str, scopes: list[str], labels: dict[str, str]
) -> UsageRow:
    def value(t: Totals) -> float:
        return t.amount if meter.measure == "amount" else t.count

    today = usage.today(meter.key, scope)
    month = usage.month(meter.key, scope)
    refused = usage.today(f"{meter.key}.refused", scope).count
    limit = usage.limit_for(meter.key, scope)
    label = meter.label
    if len(scopes) > 1 or (scope and scope in labels):
        label = labels.get(scope) or f"{meter.label} {scopes.index(scope) + 1}"
    day = usage.day(meter.key)
    return UsageRow(
        label=label,
        unit=meter.unit,
        today=value(today),
        month=value(month),
        per_day=limit.per_day if limit else None,
        per_month=limit.per_month if limit else None,
        refused=refused,
        estimate=usage.estimate(meter.key, scope),
        day_of_month=day.day,
        days_in_month=calendar.monthrange(day.year, day.month)[1],
    )


def backend_labels(services: Services) -> dict[str, str]:
    """The AI page's label for each backend, by id; a label two backends share gets a
    number, so two people's "Gemini (free tier)" are told apart without their names."""
    rows = services.store.db.query("SELECT id, label FROM ai_backends ORDER BY id")
    seen: dict[str, int] = {}
    out: dict[str, str] = {}
    for row in rows:
        label = str(row["label"])
        seen[label] = seen.get(label, 0) + 1
        out[str(row["id"])] = label if seen[label] == 1 else f"{label} {seen[label]}"
    return out


# ----- in words ---------------------------------------------------------------------------


def number(value: float) -> str:
    return f"{value:,.0f}"


def money(value: float) -> str:
    return f"about ${value:,.2f}" if value >= 0.01 else "under 1¢"


def today_words(row: UsageRow) -> str:
    if row.monthly:
        return f"{number(row.month)} of {number(row.per_month or 0)}"
    if row.per_day:
        return f"{number(row.today)} of {number(row.per_day)}"
    return f"{number(row.today)} {row.unit}"


def month_words(row: UsageRow) -> str:
    if row.monthly:
        return f"about {number(row.projected or 0)} by the {_ordinal(row.days_in_month)}"
    words = f"{number(row.month)} {row.unit}"
    if row.estimate is not None:
        words = f"{money(row.estimate)} · {words}"
    return words


def usage_text(data: UsageData) -> str:
    """The card in words, for a channel without pictures or a drawing that failed."""
    if not data.groups:
        return NOTHING
    lines = ["Usage today:"]
    for group in data.groups:
        for row in group.rows:
            if row.monthly:
                line = f"- {row.label}: {today_words(row)} this month"
            elif row.per_day:
                line = f"- {row.label}: {today_words(row)} today"
            else:
                line = f"- {row.label}: {today_words(row)} today (no limit known)"
            if row.refused:
                line += f", refused {_times(row.refused)}"
            if row.estimate is not None:
                line += f"; {money(row.estimate)} this month"
            lines.append(line)
    return "\n".join(lines)


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ----- drawing it -------------------------------------------------------------------------


def view(data: UsageData, theme: str = "light") -> dict[str, Any]:
    colors = {**THEMES[theme], **USAGE_COLORS[theme]}
    y = 92.0
    groups = []
    for group in data.groups:
        head_y = y + 18
        rows = []
        y += GROUP_H
        for row in group.rows:
            base = y + 6
            share = row.share
            bar = None
            if share is not None:
                bar = {
                    "width": round(BAR_W * min(max(share, 0.0), 1.0), 1),
                    "fill": colors[row.state],
                    "pace": BAR_X + BAR_W * row.pace if row.pace is not None else None,
                    "heading": (
                        BAR_X + BAR_W * min((row.projected or 0) / (row.per_month or 1), 1.0)
                        if row.monthly
                        else None
                    ),
                }
            value = today_words(row)
            if row.refused:
                value = f"refused {_times(row.refused)}"
            rows.append(
                {
                    "y": base,
                    "label": fit(row.label, 13, LABEL_W, bold=True),
                    "bar": bar,
                    "none": "No limit known" if share is None else "",
                    "value": fit(value, 13, VALUE_W),
                    "month": fit(month_words(row), 12, WIDTH - PAD - VALUE_X - VALUE_W - 12),
                }
            )
            y += ROW_H
        groups.append({"name": group.name, "y": head_y, "rows": rows})
        y += 8
    spark = None
    if data.ai_days:
        top = y + 28
        hi = max(data.ai_days) or 1
        step = BAR_W / (len(data.ai_days) - 1)
        points = [
            (BAR_X + i * step, top + SPARK_H - 8 - (v / hi) * (SPARK_H - 16))
            for i, v in enumerate(data.ai_days)
        ]
        spark = {
            "y": y + 18,
            "top": top,
            "points": " ".join(f"{px:.1f},{py:.1f}" for px, py in points),
            "dot": {"x": round(points[-1][0], 1), "y": round(points[-1][1], 1)},
            "peak": number(hi),
        }
        y = top + SPARK_H
    height = max(y + PAD, 160.0)
    return {
        "width": WIDTH,
        "height": height,
        "pad": PAD,
        "c": colors,
        "title": f"Usage, {data.day:%A} {data.day.day} {data.day:%B}",
        "bar_x": BAR_X,
        "bar_w": BAR_W,
        "value_x": VALUE_X,
        "groups": groups,
        "spark": spark,
        "empty": NOTHING if not data.groups else "",
    }


USAGE_COLORS: dict[str, dict[str, str]] = {
    "light": {"good": "#3F8F6B", "near": "#D99A2B", "over": "#C9483B"},
    "dark": {"good": "#5DB48C", "near": "#E0A73F", "over": "#E5675A"},
}


def usage_svg(data: UsageData, theme: str = "light") -> str:
    return write_svg("usage_card.svg", **view(data, theme))


# ----- sending it -------------------------------------------------------------------------


class UsageCard:
    def __init__(self, services: Services) -> None:
        self.services = services

    def data(self) -> UsageData:
        return collect(self.services.usage, backend_labels(self.services))

    def svg(self, member: Member) -> str:
        from themi.standard.drawings import DrawingsPreferences

        prefs = self.services.store.preferences(member.id, DrawingsPreferences)
        return usage_svg(self.data(), prefs.picture_theme)

    async def send(self, member: Member) -> bool:
        """The card as a picture, to an admin; the words when it can't be drawn. True when
        a picture went. Anyone else is told it's for the admins."""
        from themi.channels.outbox import Priority

        if not member.is_admin:
            await self.services.outbox.send(member, NOT_ADMIN, priority=Priority.REPLY)
            return False
        data = self.data()
        drawings = self.services.maybe(keys.drawings)
        png = await drawings.png(self.svg(member), PNG_WIDTH) if drawings is not None else None
        if png is not None:
            sent = await self.services.outbox.send_photo(member, png, CAPTION, kind="usage")
            if sent is not None:
                return True
        await self.services.outbox.send(
            member, usage_text(data), priority=Priority.REPLY, kind="usage"
        )
        return False
