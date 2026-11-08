"""The Accounts page (CR17a): a core page made of the loaded modules' sections.

Each module that links something adds a section with `ctx.accounts_section`: a member's own
(their Google accounts, their music) come first, in order; the household's (the appliances,
the family calendar...) are rows under "Household connections", which only admins see, as
are the routes behind them. A module left out takes its section with it.

The household rows keep their old /family/... addresses (bookmarks, and the Home Connect
callback registered with Home Connect), and each lands back here with its row open.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from themi.accounts import Member
from themi.web.auth import Session
from themi.web.kit import Kit


def back(row: str) -> str:
    """The Accounts page with this connection's row open."""
    return f"/accounts?open={row}#{row}"


def household_models(app: Any) -> dict[str, Any]:
    """CR7c: the loaded modules' household settings models, by module."""
    return {model.module: model for model in app.services.household_models}


def household_settings(app: Any) -> dict[str, Any]:
    return {name: app.store.household(model) for name, model in household_models(app).items()}


def accounts_values(app: Any, member: Member, **extra: Any) -> dict[str, Any]:
    """Everything accounts.html shows this member: each section's template and values. The
    household's rows read theirs from `household`, which is None for a member who isn't
    an admin."""
    sections: list[str] = []
    household_sections: list[str] = []
    values: dict[str, Any] = {}
    household: dict[str, Any] = {"settings": household_settings(app)} if member.is_admin else {}
    for section in sorted(app.services.accounts_sections, key=lambda s: s.order):
        if section.household and not member.is_admin:
            continue
        shown = section.values(member) if section.values else {}
        if shown is None:  # the module has nothing to show here
            continue
        (household if section.household else values).update(shown)
        (household_sections if section.household else sections).append(section.template)
    return {
        **values,
        "sections": sections,
        "household_sections": household_sections,
        "household": household if member.is_admin else None,
        **extra,
    }


def render(kit: Kit, request: Request, session: Session, flash: str, **extra: Any) -> HTMLResponse:
    """The page shown in place, for a step whose answer stays out of the URL (the address
    Roborock emailed a code to)."""
    return kit.page(
        request,
        "accounts.html",
        member=session.member,
        csrf=session.csrf_token,
        flash=flash,
        **accounts_values(kit.app, session.member, **extra),
    )


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()

    @router.get("/accounts", response_class=HTMLResponse)
    def accounts_page(request: Request, opened: str = Query("", alias="open")) -> HTMLResponse:
        session = kit.current(request)
        return kit.with_flash(
            request,
            "accounts.html",
            session,
            **accounts_values(kit.app, session.member, opened=opened),
        )

    return router
