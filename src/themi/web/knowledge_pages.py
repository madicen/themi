"""Rules and memory: locked rules, your drafts, remembered facts, and the repair log.

Facts shown are household facts plus the member's own personal ones;
nothing else can be seen or edited, whatever a form says.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import Member, NotFound, PermissionDenied
from themi.core.memory import Fact, Memory
from themi.core.rules import RuleError
from themi.web.kit import Kit


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def memory() -> Memory:
        assert app.services.memory is not None
        return app.services.memory

    @router.get("/knowledge", response_class=HTMLResponse)
    def knowledge_page(request: Request, q: str = "") -> HTMLResponse:
        session = kit.current(request)
        member = session.member
        journal = app.services.journal
        query = q.strip()[:200]
        entries = (
            []
            if journal is None
            else journal.search(member, query, limit=20)
            if query
            else journal.recent(member)
        )
        return kit.with_flash(
            request,
            "knowledge.html",
            session,
            locked=app.rulebook.household(),
            personal=app.rulebook.personal(member),
            drafts=app.rulebook.drafts(member),
            facts=memory().visible(member),
            repairs=list(reversed(memory().repairs(member.id)))[:20],
            entries=entries,
            query=query,
        )

    # ----- the journal (M1) ---------------------------------------------------------

    @router.post("/journal/{entry_id}/delete")
    async def delete_entry(request: Request, entry_id: int) -> Response:
        session, _ = await kit.checked(request)
        journal = app.services.journal
        if journal is None or not journal.delete(session.member, entry_id):
            return kit.redirect("/knowledge", "That entry isn't one of yours.")
        return kit.redirect("/knowledge", "Deleted that day from your journal.")

    # ----- rules ------------------------------------------------------------------

    @router.post("/rules/{rule_id}/{change}")
    async def change_rule(request: Request, rule_id: int, change: str) -> Response:
        session, _ = await kit.checked(request)
        rulebook = app.rulebook
        try:
            if change == "lock":
                message = await rulebook.lock(rule_id, session.member)
            elif change == "discard":
                message = await rulebook.discard(rule_id, session.member)
            elif change == "retire":
                rulebook.unlock(rule_id, session.member)
                message = "That rule is retired."
            else:
                return kit.page(request, "message.html", 404, title="Not found", body="")
        except (RuleError, PermissionDenied, NotFound) as exc:
            message = str(exc) or "That one can't be changed from here."
        return kit.redirect("/knowledge", message)

    # ----- facts ------------------------------------------------------------------

    def editable(member: Member, fact_id: int) -> Fact | None:
        try:
            fact = memory().get(fact_id)
        except NotFound:
            return None
        return fact if memory().can_edit(member, fact) else None

    @router.post("/facts/{fact_id}/{change}")
    async def change_fact(request: Request, fact_id: int, change: str) -> Response:
        session, form = await kit.checked(request)
        fact = editable(session.member, fact_id)
        if fact is None:
            return kit.redirect("/knowledge", "That fact isn't one you can change.")
        if change == "pin":
            memory().pin(fact.id, True)
            message = "Pinned: it's always in front of Themi now."
        elif change == "unpin":
            memory().pin(fact.id, False)
            message = "Unpinned: it comes up when it's relevant."
        elif change == "edit":
            text = str(form.get("fact", "")).strip()
            if not text:
                return kit.redirect("/knowledge", "A fact needs some words.")
            memory().correct(fact.id, text)
            message = "Updated."
        elif change == "delete":
            memory().forget(fact.id)
            message = "Forgotten."
        else:
            return kit.page(request, "message.html", 404, title="Not found", body="")
        return kit.redirect("/knowledge", message)

    return router
