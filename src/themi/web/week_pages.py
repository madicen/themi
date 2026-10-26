"""My week: how Themi sees your coming week, in words (S3).

Only ever your own: no route takes a member id, whatever a form or URL says.
Corrections nudge your learned week a little (themi.energy.week.correct).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.energy.model import EnergyModel
from themi.energy.week import DAY_NAMES, correct, good_moments, learned_from, week_view
from themi.web.kit import Kit


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def energy() -> EnergyModel:
        model = app.services.energy
        assert isinstance(model, EnergyModel)
        return model

    @router.get("/week", response_class=HTMLResponse)
    def week_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        member = session.member  # always the signed-in person
        return kit.with_flash(
            request,
            "week.html",
            session,
            days=week_view(energy(), member),
            moments=good_moments(energy(), member),
            learned=learned_from(energy(), member),
            day_names=DAY_NAMES,
            tz_info=ZoneInfo(energy().timezone),
        )

    @router.post("/week/correct")
    async def correct_week(request: Request) -> Response:
        session, form = await kit.checked(request)
        part = str(form.get("part", ""))
        way = str(form.get("way", ""))
        try:
            weekday = int(str(form.get("weekday", "")))
            if way not in ("better", "worse"):
                raise ValueError(way)
            correct(energy(), session.member, weekday, part, better=way == "better")
        except ValueError:
            return kit.redirect("/week", "That part of the week couldn't be changed.")
        lean = "a bit better" if way == "better" else "a bit lower"
        return kit.redirect(
            "/week", f"Thanks. {DAY_NAMES[weekday]} {part}s will lean {lean} from now on."
        )

    return router
