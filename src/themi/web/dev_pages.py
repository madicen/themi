"""Development, for admins (D3a): updating or restarting the server, and how replies went
(what was `/ai/timing`: reply times, how often more tools were needed, replies marked
wrong).

The buttons only ask: Themi writes a request for the host's runner, through the trust
tiers (themi.updates).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from themi.core.timing import hedges, medians, router_numbers, week_of_replies
from themi.core.wrong_replies import LABEL_WORDS, ReplyReview
from themi.updates import ControlError
from themi.web.kit import Kit

SLOWEST = 10
STATE_WORDS = {
    "waiting": "waiting for the server to pick it up",
    "running": "under way",
    "done": "done",
    "failed": "didn't work",
    "refused": "turned down by the runner",
    "lapsed": "never picked up",
}


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    @router.get("/dev", response_class=HTMLResponse)
    def dev_page(request: Request) -> HTMLResponse:
        """D3a: the server card. Ideas #51 and #55: the week's replies, the medians, and
        where the slowest ones' time went. P3: how often the tool groups sent at the start
        were enough. P4: the week's replies marked wrong, and their labels. P2b: slow calls
        sent twice."""
        session = kit.admin(request)
        replies = week_of_replies(app.db)
        marked, labels = ReplyReview(app.db).week()
        names = {m.id: m.name for m in app.store.list_members()}
        return kit.with_flash(
            request,
            "dev.html",
            session,
            server=app.server.state(),
            state_words=STATE_WORDS,
            count=len(replies),
            medians=medians(replies),
            noticed=sum(1 for r in replies if r.slow_notice),
            hedged=hedges(app.db),
            router=router_numbers(replies),
            marked=marked,
            labels=[(LABEL_WORDS[name], n) for name, n in labels.most_common()],
            unlabelled=marked - labels.total(),
            slowest=sorted(replies, key=lambda r: -r.seconds)[:SLOWEST],
            names=names,
        )

    @router.get("/ai/timing")
    def old_timing_page(request: Request) -> Response:
        kit.admin(request)
        return RedirectResponse("/dev", status_code=303)

    @router.post("/dev/server/{action}")
    async def ask_server(request: Request, action: str) -> Response:
        session, _ = await kit.checked(request, admin=True)
        try:
            message = await app.server.request(action, session.member)
        except ControlError as exc:
            message = str(exc)
        return kit.redirect("/dev", message)

    return router
