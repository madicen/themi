"""My AI: each member's own backends, task chains and connection tests. (How long replies
take, P2a, is on the Development page now: dev_pages.)

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
from themi.core.capabilities import IMAGE_GENERATION, VOICE_NOTES
from themi.storage.secrets import Secret
from themi.web.kit import Kit

MAX_CHAIN = 3
TASK_LABELS = {
    AITask.CONVERSATION: "Conversation",
    AITask.PDA_REWRITE: "Rewording messages gently",
    AITask.EMAIL_TRIAGE: "Email triage",
    AITask.STRUCTURED_MISC: "Other quick jobs (meal ideas, call scripts)",
    AITask.TRANSCRIPTION: "Voice notes",
    AITask.EMBEDDING: "Choosing which tools a message needs (an embedding model, not a chat one)",
    AITask.CHAT: "Conversation mode: the chat reply",
    AITask.SIDECAR: "Conversation mode: picking out tasks in the background",
    AITask.RECIPES: "Recipes: reading ingredients, prep and recipe pages",
    AITask.BODY_DOUBLE_STEPS: "Body double: steps for a guided session",
    AITask.EXPENSE_SHEET_FIELDS: "Expense sheets: the fields a new sheet has",
    AITask.STEP_IMAGE: "Pictures for guided steps (Gemini or OpenAI image models)",
}
KIND_LABELS = {
    "gemini": "Gemini",
    "anthropic": "Claude",
    "ollama": "Ollama (local)",
    "lm_studio": "LM Studio (local)",
    "openai_compat": "Other OpenAI-compatible server",
    "cloudflare": "Cloudflare Workers AI (pictures only)",
}


# CR19: tasks that only run when a capability is loaded.
TASK_CAPABILITY = {AITask.TRANSCRIPTION: VOICE_NOTES, AITask.STEP_IMAGE: IMAGE_GENERATION}

MAX_IMAGE_CAP = 100
MAX_PICTURE_CAP = 500  # F34gb: pictures sent in chat


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app
    ai = app.ai_settings

    def shown(task: AITask) -> bool:
        """CR19: a task whose capability isn't loaded has nothing to set up."""
        needs = TASK_CAPABILITY.get(task)
        return needs is None or needs in app.services.capabilities

    def values(member: Member, **extra: Any) -> dict[str, Any]:
        ai.ensure_defaults(member.id)
        backends = ai.backends(member.id)
        chains = {}
        for task in AITask:
            entries = ai.chain(member.id, task)
            slots = [(e.backend_id, e.model or "") for e in entries]
            slots += [(None, "")] * (MAX_CHAIN - len(slots))
            chains[task] = slots[:MAX_CHAIN]
        loaded = app.services.ai_adapters  # CR19: the AI provider modules' kinds only
        return {
            "backends": backends,
            "chains": chains,
            "task_labels": {t: w for t, w in TASK_LABELS.items() if shown(t)},
            "kinds": [(k, KIND_LABELS[k]) for k in ADAPTER_KINDS if not loaded or k in loaded],
            "kind_labels": KIND_LABELS,
            "image_cap": app.services.router.image_cap(member.id),  # BD4a
            "picture_cap": picture_cap(member.id),  # F34gb
            **extra,
        }

    @router.get("/ai", response_class=HTMLResponse)
    def ai_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        return kit.with_flash(request, "ai.html", session, **values(session.member))

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
            "supports_images": form.get("supports_images") == "on",
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

    @router.post("/ai/image-cap")
    async def save_image_cap(request: Request) -> Response:
        """BD4a: their own cap on pictures a day (only their own: the session's member)."""
        session, form = await kit.checked(request)
        try:
            cap = int(str(form.get("image_daily_cap", "")))
            if not 0 <= cap <= MAX_IMAGE_CAP:
                raise ValueError(cap)
        except ValueError:
            return kit.redirect("/ai", f"Pictures a day is a number from 0 to {MAX_IMAGE_CAP}.")
        app.db.execute(
            "UPDATE members SET image_daily_cap = ? WHERE id = ?", (cap, session.member.id)
        )
        return kit.redirect("/ai", f"At most {cap} pictures a day.")

    def picture_cap(member_id: int) -> int:
        row = app.db.one("SELECT picture_daily_cap FROM members WHERE id = ?", (member_id,))
        return int(row["picture_daily_cap"]) if row else 0

    @router.post("/ai/picture-cap")
    async def save_picture_cap(request: Request) -> Response:
        """F34gb: their own cap on pictures sent in chat that Themi looks at a day."""
        session, form = await kit.checked(request)
        try:
            cap = int(str(form.get("picture_daily_cap", "")))
            if not 0 <= cap <= MAX_PICTURE_CAP:
                raise ValueError(cap)
        except ValueError:
            return kit.redirect(
                "/ai", f"Pictures looked at a day is a number from 0 to {MAX_PICTURE_CAP}."
            )
        app.db.execute(
            "UPDATE members SET picture_daily_cap = ? WHERE id = ?", (cap, session.member.id)
        )
        return kit.redirect("/ai", f"I'll look at up to {cap} of your pictures a day.")

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
