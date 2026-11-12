"""Expense sheets as CSV, with an audit trail (EX3).

One row per entry: its number, the sheet's fields, then for each field its status (in
words, as on the website) and how sure it is, then where its values came from (the source
types) and links to them (the receipt in Gmail, the calendar event). Money is written as
84.20, dates as YYYY-MM-DD. Only for people who can see the sheet, and only when its CSV is
on (`/expenses/<sheet id>.csv`, and "send me the travel sheet for October" in chat).
`/spending/business.csv` stays X1's own export, read from the Business sheet.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from typing import Any

from themi_home.expense_sheets import ExpenseSheets
from themi_home.expenses import STATUS_WORDS, Field, Sheet


class RangeError(ValueError):
    """A date range that can't be read, in words."""


def month_range(today: date) -> tuple[date, date]:
    """This month: its first day and its last."""
    first = today.replace(day=1)
    return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def read_range(start: str, end: str, today: date) -> tuple[date, date]:
    """`from` and `to` (both kept, YYYY-MM-DD); either left out is this month's."""
    first, last = month_range(today)
    try:
        lo = date.fromisoformat(start) if start.strip() else first
        hi = date.fromisoformat(end) if end.strip() else (
            last if not start.strip() else month_range(lo)[1]
        )  # fmt: skip
    except ValueError as exc:
        raise RangeError("dates are written like 2026-10-01") from exc
    if hi < lo:
        raise RangeError("the end comes before the start")
    return lo, hi


def cell(f: Field, value: Any) -> str:
    if value is None:
        return ""
    if f.type == "money":
        return f"{int(value) / 100:.2f}"
    if f.type == "number":
        return f"{value:g}" if isinstance(value, int | float) else str(value)
    return str(value)


def sheet_csv(sheets: ExpenseSheets, sheet: Sheet, start: date, end: date) -> str:
    expenses = sheets.expenses
    fields = expenses.fields(sheet.id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "expense",
            *(f.label for f in fields),
            *(part for f in fields for part in (f"{f.label} status", f"{f.label} confidence")),
            "source",
            "source link",
        ]
    )
    for entry in expenses.entries([sheet.id], start, end + timedelta(days=1)):
        values, audit, sources, links = [], [], [], []
        for f in fields:
            value = entry.values.get(f.key)
            if value is None or value.value is None:
                values.append("")
                audit += [STATUS_WORDS["missing"] if f.critical else "", ""]
                continue
            values.append(cell(f, value.value))
            audit += [
                STATUS_WORDS[value.status],
                "" if value.confidence is None else f"{value.confidence:.2f}",
            ]
            if value.source_type not in sources:
                sources.append(value.source_type)
            link = sheets.link(value)
            if link and link not in links:
                links.append(link)
        writer.writerow([entry.id, *values, *audit, "; ".join(sources), " ".join(links)])
    return out.getvalue()


def filename(sheet: Sheet, start: date, end: date) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", sheet.title.lower()).strip("-") or "sheet"
    first, last = month_range(start)
    when = f"{start:%Y-%m}" if (start, end) == (first, last) else f"{start}-to-{end}"
    return f"{slug}-{when}.csv"
