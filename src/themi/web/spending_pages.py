"""Spending (X1): the household's takeout and eating out, and your own business expenses,
a month at a time, with your business expenses as a CSV to download.

Business expenses are only ever your own: no route takes a member id.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.core.spending import KIND_WORDS, Spending, money, month_of
from themi.core.tools import ToolFailed
from themi.web.kit import Kit


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def spending() -> Spending:
        assert app.services.spending is not None
        return app.services.spending

    def month(request: Request) -> date:
        try:
            return month_of(request.query_params.get("month", ""), spending().today())
        except ToolFailed:
            return spending().today().replace(day=1)

    @router.get("/spending", response_class=HTMLResponse)
    def spending_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        first = month(request)
        spends = spending().month(first, business_of=session.member)
        previous = (first.replace(day=1) - date.resolution).replace(day=1)
        return kit.with_flash(
            request,
            "spending.html",
            session,
            month=first,
            previous=previous,
            rows=[
                {
                    "on": s.spent_on,
                    "place": s.place or "somewhere",
                    "amount": money(s.amount_cents),
                    "kind": KIND_WORDS[s.kind],
                    "business": s.business,
                    "who": app.store.get_member(s.member_id).name,
                    "receipt": s.email_id is not None,
                }
                for s in spends
            ],
            takeout=spending().takeout_words()
            if first == spending().today().replace(day=1)
            else "",
            business_total=money(sum(s.amount_cents for s in spends if s.business)),
        )

    @router.get("/spending/business.csv")
    def business_csv(request: Request) -> Response:
        session = kit.current(request)
        first = month(request)
        return Response(
            spending().business_csv(session.member, first),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="business-{first:%Y-%m}.csv"'},
        )

    return router
