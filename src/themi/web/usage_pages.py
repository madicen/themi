"""The Usage page (UC5; the Themi Usage Plan's "Limits" and "Where it shows").

`/admin/usage`, for admins: the usage card as SVG in the page, then each meter with its
last 30 days and the limit in use, where that limit came from, and a form to set the
household's own in its place (or go back to the module's). A module's limit checked more
than six months ago is marked "check this".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from markupsafe import Markup

from themi.standard.usage_card import (
    UsageCard,
    backend_labels,
    collect,
    number,
    usage_svg,
)
from themi.usage import GROUPS, Limit, Meter, UsageBook
from themi.web.kit import Kit

STALE_MONTHS = 6


@dataclass(frozen=True)
class MeterView:
    key: str
    label: str
    group: str
    module: str
    unit: str
    today: str
    month: str
    days: str  # the last 30 days' total
    busiest: str
    limit: Limit | None
    stale: bool

    @property
    def limit_words(self) -> str:
        if self.limit is None:
            return "No limit known"
        parts = []
        if self.limit.per_day is not None:
            parts.append(f"{number(self.limit.per_day)} a day")
        if self.limit.per_month is not None:
            parts.append(f"{number(self.limit.per_month)} a month")
        return ", ".join(parts)

    @property
    def source_words(self) -> str:
        limit = self.limit
        if limit is None:
            return ""
        if limit.overridden:
            return f"Set by {limit.set_by}"
        bits = [b for b in (limit.source, f"checked {limit.checked}" if limit.checked else "") if b]
        return "From the module: " + ", ".join(bits) if bits else "From the module"


def stale(checked: str, today: date) -> bool:
    """A "YYYY-MM" more than six months before today."""
    try:
        year, month = (int(p) for p in checked.split("-")[:2])
    except ValueError:
        return False
    return (today.year - year) * 12 + (today.month - month) > STALE_MONTHS


def meter_views(usage: UsageBook) -> list[MeterView]:
    order = {name: i for i, name in enumerate(GROUPS)}
    views = []
    meters: list[Meter] = sorted(
        usage.meters.values(), key=lambda m: (order.get(m.group, 99), m.order, m.label)
    )
    for meter in meters:
        amount = meter.measure == "amount"

        def value(t: Any, amount: bool = amount) -> float:
            return t.amount if amount else t.count

        days = [value(t) for _, t in usage.days(meter.key, 30)]
        limit = usage.limit_for(meter.key)
        views.append(
            MeterView(
                key=meter.key,
                label=meter.label,
                group=meter.group,
                module=meter.module,
                unit=meter.unit,
                today=number(value(usage.today(meter.key))),
                month=number(value(usage.month(meter.key))),
                days=number(sum(days)),
                busiest=number(max(days) if days else 0),
                limit=limit,
                stale=bool(
                    limit and not limit.overridden and limit.checked
                    and stale(limit.checked, usage.day(meter.key))
                ),
            )
        )  # fmt: skip
    return views


def _number(raw: object) -> float | None:
    """A limit from the form: blank is none; anything else a whole number, not negative."""
    text = str(raw or "").replace(",", "").strip()
    if not text:
        return None
    value = float(text)
    if value < 0 or value != int(value):
        raise ValueError(text)
    return value


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    @router.get("/admin/usage", response_class=HTMLResponse)
    def usage_page(request: Request) -> HTMLResponse:
        session = kit.admin(request)
        usage = app.services.usage
        from themi.standard.drawings import DrawingsPreferences

        theme = app.store.preferences(session.member.id, DrawingsPreferences).picture_theme
        data = collect(usage, backend_labels(app.services))
        # The template escaped every word from data; the SVG is Themi's own markup.
        card = Markup(usage_svg(data, theme))
        return kit.with_flash(request, "usage.html", session, card=card, meters=meter_views(usage))

    @router.post("/admin/usage/{key}/limit")
    async def set_limit(request: Request, key: str) -> Response:
        session, form = await kit.checked(request, admin=True)
        usage = app.services.usage
        meter = usage.meters.get(key)
        if meter is None:
            return kit.page(request, "message.html", 404, title="Not found", body="")
        back = f"/admin/usage#meter-{key}"
        if form.get("clear"):
            usage.clear_limit(key)
            return kit.redirect(
                f"/admin/usage#meter-{key}", f"{meter.label}: back to the module's limit."
            )
        try:
            per_day, per_month = _number(form.get("per_day")), _number(form.get("per_month"))
        except ValueError:
            return kit.redirect(back, "A limit is a whole number, or blank.")
        if per_day is None and per_month is None:
            return kit.redirect(
                f"/admin/usage#meter-{key}",
                "Give a daily or monthly limit, or go back to the module's.",
            )
        usage.set_limit(key, per_day=per_day, per_month=per_month, set_by=session.member.name)
        return kit.redirect(
            f"/admin/usage#meter-{key}", f"{meter.label}: the household's limit is saved."
        )

    return router


__all__ = ["UsageCard", "routes"]
