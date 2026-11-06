"""Recipes on the website (RC1a, RC6).

RC1a: the cookbook page under Accounts. A person picks the family's recipe doc in Google's
file picker (scope `drive.file`, so Themi can open that file and nothing else of theirs);
pasting the doc's link also works where Google already lets Themi open it (a doc picked
before, or `make dev`'s fake). The picker page is the one page that loads Google's own
scripts, so it gets its own, wider Content-Security-Policy.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import LinkedAccount, Member
from themi.connectors.gdocs import DocsError, doc_id_from
from themi.connectors.google import DRIVE_FILE_SCOPE
from themi.core.recipes import Recipes
from themi.web.kit import Kit

PICKER_HEADER = "X-Themi-Page"  # read and removed by the site's security headers


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def recipes() -> Recipes | None:
        return app.services.recipes

    def own_account(member: Member, account_id: int) -> LinkedAccount | None:
        return next((a for a in app.store.linked_accounts(member.id) if a.id == account_id), None)

    @router.get("/accounts/{account_id}/cookbook", response_class=HTMLResponse)
    def cookbook_page(request: Request, account_id: int) -> Response:
        session = kit.current(request)
        account = own_account(session.member, account_id)
        book = recipes()
        if account is None or book is None or not book.ready():
            return kit.redirect("/accounts", "That account isn't one of yours.")
        if not account.allows(DRIVE_FILE_SCOPE):
            return kit.redirect(
                "/accounts",
                "Link this account again (with Google Drive ticked) to pick the cookbook.",
            )
        config = book.config
        assert config is not None
        settings = book.settings()
        response = kit.with_flash(
            request,
            "cookbook.html",
            session,
            account=account,
            cookbook=settings,
            chosen_here=settings["account_id"] == account.id,
            picker=bool(config.picker_api_key and config.project_number),
            client_id=config.client_id,
            picker_key=config.picker_api_key,
            project_number=config.project_number,
            looks=[r for r in book.all(include_charts=True) if r.needs_look],
        )
        response.headers[PICKER_HEADER] = "picker"
        return response

    @router.post("/accounts/{account_id}/cookbook")
    async def choose_cookbook(request: Request, account_id: int) -> Response:
        session, form = await kit.checked(request)
        book = recipes()
        back = f"/accounts/{account_id}/cookbook"
        if book is None:
            return kit.redirect("/accounts", "Recipes aren't set up on this server.")
        doc_id = doc_id_from(str(form.get("doc", "")))
        if doc_id is None:
            return kit.redirect(back, "That doesn't look like a Google Doc's link.")
        try:
            said = await book.choose(session.member, account_id, doc_id)
        except DocsError as exc:
            return kit.redirect(back, str(exc))
        return kit.redirect(back, said)

    @router.post("/accounts/{account_id}/cookbook/read")
    async def read_now(request: Request, account_id: int) -> Response:
        await kit.checked(request)
        book = recipes()
        back = f"/accounts/{account_id}/cookbook"
        if book is None or book.doc_id is None:
            return kit.redirect(back, "There's no cookbook yet.")
        result = await book.sync(force=True)
        if result is None:
            return kit.redirect(
                back, book.settings()["problem"] or "The cookbook couldn't be read."
            )
        return kit.redirect(back, book.summary(result))

    return router
