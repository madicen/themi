"""My AI: each member's own backends, task chains and connection tests. Also, for admins,
how long replies take (P2a).

Keys are write-only. The page never renders a key, not even masked
characters of it; it only says whether one is saved. Leaving the key field
blank keeps the saved key; "remove saved key" clears it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import InvalidValue, Member, NotFound, PermissionDenied
from themi.ai.settings import ADAPTER_KINDS, AITask, RouteEntry
from themi.core.timing import medians, router_numbers, week_of_replies
from themi.storage.secrets import Secret
from themi.web.kit import Kit

MAX_CHAIN = 3
SLOWEST = 10
TASK_LABELS = {
    AITask.CONVERSATION: "Conversation",
    AITask.PDA_REWRITE: "Rewording messages gently",
    AITask.EMAIL_TRIAGE: "Email triage",
    AITask.STRUCTURED_MISC: "Other quick jobs (meal ideas, call scripts)",
    AITask.TRANSCRIPTION: "Voice notes",
    AITask.EMBEDDING: "Choosing which tools a message needs (embeddings, Gemini only)",
}
KIND_LABELS = {
    "gemini": "Gemini",
    "anthropic": "Claude",
    "ollama": "Ollama (local)",
    "lm_studio": "LM Studio (local)",
    "openai_compat": "Other OpenAI-compatible server",
}


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app
    ai = app.ai_settings

    def values(member: Member, **extra: Any) -> dict[str, Any]:
        ai.ensure_defaults(member.id)
        backends = ai.backends(member.id)
        chains = {}
        for task in AITask:
            entries = ai.chain(member.id, task)
            slots = [(e.backend_id, e.model or "") for e in entries]
            slots += [(None, "")] * (MAX_CHAIN - len(slots))
            chains[task] = slots[:MAX_CHAIN]
        return {
            "backends": backends,
            "chains": chains,
            "task_labels": TASK_LABELS,
            "kinds": [(k, KIND_LABELS[k]) for k in ADAPTER_KINDS],
            "kind_labels": KIND_LABELS,
            **extra,
        }

    @router.get("/ai", response_class=HTMLResponse)
    def ai_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        return kit.with_flash(request, "ai.html", session, **values(session.member))

    @router.get("/ai/timing", response_class=HTMLResponse)
    def timing_page(request: Request) -> HTMLResponse:
        """Ideas #51 and #55: the week's replies, the medians, and where the slowest
        ones' time went. P3: how often the tool groups sent at the start were enough."""
        session = kit.admin(request)
        replies = week_of_replies(app.db)
        names = {m.id: m.name for m in app.store.list_members()}
        return kit.with_flash(
            request,
            "timing.html",
            session,
            count=len(replies),
            medians=medians(replies),
            noticed=sum(1 for r in replies if r.slow_notice),
            router=router_numbers(replies),
            slowest=sorted(replies, key=lambda r: -r.seconds)[:SLOWEST],
            names=names,
        )

    def backend_fields(form: dict[str, Any]) -> dict[str, Any]:
        timeout = str(form.get("timeout") or "60")
        try:
            timeout_value = float(timeout)
        except ValueError as exc:
            raise InvalidValue(f"{timeout!r} isn't a number of seconds") from exc
        return {
            "model": str(form.get("model", "")),
            "base_url": str(form.get("base_url", "")) or None,
            "timeout": timeout_value,
            "supports_tools": form.get("supports_tools") == "on",
            "supports_structured": form.get("supports_structured") == "on",
            "supports_audio": form.get("supports_audio") == "on",
            "effort": str(form.get("effort", "")) or None,
        }

    def key_from(form: dict[str, Any]) -> Secret | None:
        key = str(form.get("api_key", "")).strip()
        return Secret(key) if key else None

    @router.post("/ai/backends")
    async def add_backend(request: Request) -> Response:
        session, form = await kit.checked(request)
        member = session.member
        try:
            ai.add_backend(
                member,
                member.id,
                str(form.get("label", "")),
                str(form.get("kind", "")),
                api_key=key_from(form),
                **backend_fields(form),
            )
        except InvalidValue as exc:
            return kit.page(
                request,
                "ai.html",
                400,
                member=member,
                csrf=session.csrf_token,
                **values(member, error=str(exc)),
            )
        return kit.redirect("/ai", "Added. Pick where to use it below.")

    @router.post("/ai/backends/{backend_id}")
    async def update_backend(request: Request, backend_id: int) -> Response:
        session, form = await kit.checked(request)
        member = session.member
        try:
            if form.get("remove_key") == "on":
                ai.clear_key(member, backend_id)
            ai.update_backend(
                member,
                backend_id,
                label=str(form.get("label", "")),
                api_key=key_from(form),
                **backend_fields(form),
            )
        except (InvalidValue, PermissionDenied, NotFound) as exc:
            return kit.page(
                request,
                "ai.html",
                400,
                member=member,
                csrf=session.csrf_token,
                **values(member, error=str(exc)),
            )
        return kit.redirect("/ai", "Saved.")

    @router.post("/ai/backends/{backend_id}/remove")
    async def remove_backend(request: Request, backend_id: int) -> Response:
        session, _ = await kit.checked(request)
        try:
            ai.remove_backend(session.member, backend_id)
        except (PermissionDenied, NotFound):
            return kit.redirect("/ai", "That backend isn't one of yours.")
        return kit.redirect("/ai", "Removed.")

    @router.post("/ai/chains/{task}")
    async def save_chain(request: Request, task: str) -> Response:
        session, form = await kit.checked(request)
        member = session.member
        try:
            ai_task = AITask(task)
        except ValueError:
            return kit.page(request, "message.html", 404, title="Not found", body="")
        entries = []
        for slot in range(MAX_CHAIN):
            backend = str(form.get(f"backend_{slot}", "")).strip()
            if backend:
                model = str(form.get(f"model_{slot}", "")).strip() or None
                entries.append(RouteEntry(int(backend), model))
        try:
            ai.set_chain(member, member.id, ai_task, entries)
        except (InvalidValue, PermissionDenied) as exc:
            return kit.redirect("/ai", str(exc))
        return kit.redirect("/ai", f"Saved the order for {TASK_LABELS[ai_task].lower()}.")

    @router.post("/ai/test/{task}")
    async def test_connection(request: Request, task: str) -> Response:
        session, form = await kit.checked(request)
        try:
            ai_task = AITask(task)
        except ValueError:
            return kit.page(request, "message.html", 404, title="Not found", body="")
        position = int(str(form.get("position") or 0))
        result = await app.router.test_connection(session.member.id, ai_task, position)
        if result.ok:
            message = f"{result.label} is connected ({result.model})."
        else:
            message = f"{result.label or 'That backend'} didn't answer: {result.detail}"
        if request.headers.get("HX-Request"):
            return kit.page(request, "_test_result.html", ok=result.ok, message=message)
        return kit.redirect("/ai", message)

    return router
