"""Spending (X1): the household's takeout and eating out, and your own business expenses,
a month at a time, with your business expenses as a CSV to download.

Expense sheets (EX1b): a sheet at a time (a picker of books, then their tabs), each value
with its status in words and a small mark, where it came from as a link, a tick to check
an entry, and a field editor for the sheet's owner.

Business expenses, and any sheet of someone's own, are only ever their own: no route shows
a sheet its owner isn't the one signed in.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import InvalidValue
from themi.core import keys
from themi.core.tools import ToolFailed
from themi.web.kit import Kit
from themi_home.expense_sheets import ExpenseSheets, parse_value, show
from themi_home.expenses import (
    FIELD_TYPES,
    SOURCE_WORDS,
    STATUS_MARKS,
    STATUS_WORDS,
    FieldDef,
    Sheet,
    Value,
    field_key,
)
from themi_home.spending import KIND_WORDS, Spending, money, month_of


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def spending() -> Spending:
        assert app.services.maybe(keys.spending) is not None
        return app.services.maybe(keys.spending)

    def sheets() -> ExpenseSheets:
        found = app.services.maybe(keys.expense_sheets)
        assert found is not None
        return found

    def month(request: Request) -> date:
        try:
            return month_of(request.query_params.get("month", ""), spending().today())
        except ToolFailed:
            return spending().today().replace(day=1)

    def books(member: Any) -> list[dict[str, Any]]:
        expenses = sheets().expenses
        return [
            {"book": b, "tabs": expenses.sheets(b.id)}
            for b in expenses.books(member)
            if expenses.sheets(b.id)
        ]

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
            takeout_page=app.services.maybe(keys.takeout) is not None,  # 35a
            books=books(session.member),  # EX1b
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

    def visible(request: Request, sheet_id: int) -> tuple[Any, Sheet] | None:
        session = kit.current(request)
        try:
            sheet = sheets().expenses.sheet(sheet_id)
        except InvalidValue:
            return None
        if sheet.archived_at is not None or not sheets().expenses.can_see(session.member, sheet):
            return None
        return session, sheet

    @router.get("/spending/sheets/{sheet_id}", response_class=HTMLResponse)
    def sheet_page(request: Request, sheet_id: int) -> Response:
        found = visible(request, sheet_id)
        if found is None:
            return kit.redirect("/spending", "That sheet isn't one of yours.")
        session, sheet = found
        expenses = sheets().expenses
        first = month(request)
        end = (first + timedelta(days=32)).replace(day=1)
        fields = expenses.fields(sheet.id)
        rows = []
        for entry in expenses.entries([sheet.id], first, end):
            cells = []
            for f in fields:
                value = entry.values.get(f.key)
                if value is None or value.value is None:
                    status = "missing" if f.critical else ""
                    cells.append(
                        {
                            "text": "",
                            "status": status,
                            "word": STATUS_WORDS.get(status, ""),
                            "mark": STATUS_MARKS.get(status, ""),
                            "source": "",
                            "link": "",
                        }
                    )
                    continue
                cells.append(
                    {
                        "text": show(f, value.value),
                        "status": value.status,
                        "word": STATUS_WORDS[value.status],
                        "mark": STATUS_MARKS[value.status],
                        "source": SOURCE_WORDS[value.source_type],
                        "confidence": (
                            f"{round(value.confidence * 100)}% sure"
                            if value.confidence is not None and value.status != "verified"
                            else ""
                        ),
                        "link": sheets().link(value),
                    }
                )
            checked = all(
                v.status == "verified" for v in entry.values.values() if v.value is not None
            )
            rows.append(
                {
                    "entry": entry,
                    "cells": cells,
                    "who": app.store.get_member(entry.member_id).name,
                    "checked": checked,
                    "can_check": sheets().can_check(session.member, entry, sheet),
                }
            )
        totals = [
            {"label": f.label, "total": show(f, sum(r["entry"].get(f.key) or 0 for r in rows))}
            for f in fields
            if f.type in ("money", "number")
        ]
        previous = (first - date.resolution).replace(day=1)
        return kit.with_flash(
            request,
            "expense_sheet.html",
            session,
            sheet=sheet,
            book=expenses.book(sheet.book_id),
            books=books(session.member),
            fields=fields,
            rows=rows,
            totals=totals,
            month=first,
            previous=previous,
            can_change=expenses.can_change(session.member, sheet),
            field_types=FIELD_TYPES,
        )

    @router.post("/spending/sheets/{sheet_id}/check/{entry_id}")
    async def check_entry(request: Request, sheet_id: int, entry_id: int) -> Response:
        session, _ = await kit.checked(request)
        back = f"/spending/sheets/{sheet_id}"
        try:
            text = sheets().verify(session.member, entry_id)
        except ToolFailed as exc:
            return kit.redirect(back, str(exc))
        return kit.redirect(back, text)

    @router.post("/spending/sheets/{sheet_id}/entries")
    async def add_entry(request: Request, sheet_id: int) -> Response:
        """An entry typed on the website: what they type is theirs, so checked."""
        session, form = await kit.checked(request)
        back = f"/spending/sheets/{sheet_id}"
        found = visible(request, sheet_id)
        if found is None:
            return kit.redirect("/spending", "That sheet isn't one of yours.")
        _, sheet = found
        expenses = sheets().expenses
        values: dict[str, Value] = {}
        try:
            for f in expenses.fields(sheet.id):
                value = parse_value(f, str(form.get(f"field_{f.key}", "")), sheets().today())
                if value is not None:
                    values[f.key] = Value.said(value)
            if not values:
                raise InvalidValue("nothing was filled in")
            expenses.add(sheet, session.member, values, origin="website")
        except InvalidValue as exc:
            return kit.redirect(back, f"Not added: {exc}.")
        return kit.redirect(back, "Added.")

    async def owner_form(request: Request, sheet_id: int) -> tuple[Sheet, dict] | Response:
        session, form = await kit.checked(request)
        found = visible(request, sheet_id)
        if found is None or not sheets().expenses.can_change(session.member, found[1]):
            return kit.redirect("/spending", "Only the sheet's owner changes its fields.")
        return found[1], form

    @router.post("/spending/sheets/{sheet_id}/fields")
    async def add_field(request: Request, sheet_id: int) -> Response:
        got = await owner_form(request, sheet_id)
        if isinstance(got, Response):
            return got
        sheet, form = got
        back = f"/spending/sheets/{sheet_id}"
        label = " ".join(str(form.get("label", "")).split())
        kind = str(form.get("type", "text"))
        choices = tuple(c.strip() for c in str(form.get("choices", "")).split(",") if c.strip())
        try:
            if kind not in FIELD_TYPES or not label:
                raise InvalidValue("a field needs a name and a type")
            if kind == "choice" and not choices:
                raise InvalidValue("a choice needs its choices, with commas between")
            sheets().expenses.add_field(
                sheet.id,
                FieldDef(field_key(label), label, kind, choices, form.get("critical") == "on"),  # type: ignore[arg-type]
            )
        except InvalidValue as exc:
            return kit.redirect(back, f"Not added: {exc}.")
        return kit.redirect(back, f"Added the {label} field.")

    @router.post("/spending/sheets/{sheet_id}/fields/{key}")
    async def change_field(request: Request, sheet_id: int, key: str) -> Response:
        got = await owner_form(request, sheet_id)
        if isinstance(got, Response):
            return got
        sheet, form = got
        back = f"/spending/sheets/{sheet_id}"
        try:
            if form.get("remove") == "yes":
                sheets().expenses.remove_field(sheet.id, key)
                return kit.redirect(back, "Removed that field.")
            sheets().expenses.update_field(
                sheet.id,
                key,
                label=" ".join(str(form.get("label", "")).split()) or None,
                critical=form.get("critical") == "on",
            )
        except InvalidValue as exc:
            return kit.redirect(back, f"Not changed: {exc}.")
        return kit.redirect(back, "Saved.")

    @router.post("/spending/sheets/{sheet_id}/settings")
    async def change_sheet(request: Request, sheet_id: int) -> Response:
        got = await owner_form(request, sheet_id)
        if isinstance(got, Response):
            return got
        sheet, form = got
        back = f"/spending/sheets/{sheet_id}"
        expenses = sheets().expenses
        try:
            if form.get("archive") == "yes":
                expenses.archive_sheet(sheet.id)
                return kit.redirect("/spending", f"Put away {sheet.title}. Its entries are kept.")
            title = " ".join(str(form.get("title", "")).split())
            if title and title != sheet.title:
                expenses.rename_sheet(sheet.id, title)
            position = str(form.get("position", "")).strip()
            if position.isdigit() and int(position) >= 1:
                expenses.move_tab(sheet.id, int(position) - 1)
            expenses.set_sheet_options(
                sheet.id,
                prompt_on_missing_critical=form.get("prompt") == "on",
                csv_enabled=form.get("csv") == "on",
                keywords=[k.strip() for k in str(form.get("keywords", "")).split(",") if k.strip()],
            )
        except InvalidValue as exc:
            return kit.redirect(back, f"Not changed: {exc}.")
        return kit.redirect(back, "Saved.")

    return router
