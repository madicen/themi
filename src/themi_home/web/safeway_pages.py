"""The Safeway helper (35c): connecting it, and the products it remembers. Plus the small
JSON API the helper (the Chrome extension) uses, under /api/safeway/.

- Anyone in the family can connect a helper or revoke one. A new token is shown once, on the
  page the POST returns (never in a URL or a cookie), and kept only as a hash.
- The API takes the token as a bearer token and nothing else: no session cookie, so no CSRF
  to check. A missing, wrong or revoked token is a 401. A token can only claim and answer
  cart jobs and read and set remembered products.
- What the helper sends is checked (`themi_home.safeway.check_results`) and is data:
  product names are escaped here and never reach the model.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from themi.core import keys
from themi.web.kit import Kit
from themi_home.safeway import Helper, InvalidResults, SafewayCart, check_product

MAX_BODY = 64_000


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def safeway() -> SafewayCart:
        assert app.services.maybe(keys.safeway) is not None
        return app.services.maybe(keys.safeway)

    def page(request: Request, **values: Any) -> HTMLResponse:
        session = kit.current(request)
        names = {m.id: m.name for m in app.store.list_members()}
        helpers = [(h, names.get(h.member_id, "someone")) for h in safeway().helpers()]
        return kit.with_flash(
            request,
            "safeway.html",
            session,
            helpers=helpers,
            products=safeway().products(),
            base_url=kit.ctx.base_url,
            **values,
        )

    @router.get("/safeway", response_class=HTMLResponse)
    def safeway_page(request: Request) -> HTMLResponse:
        return page(request)

    @router.post("/safeway/connect", response_class=HTMLResponse)
    async def connect(request: Request) -> HTMLResponse:
        session, _ = await kit.checked(request)
        token = safeway().connect(session.member)
        return page(request, new_token=token)

    @router.post("/safeway/helpers/{helper_id}/revoke")
    async def revoke(request: Request, helper_id: int) -> Response:
        await kit.checked(request)
        if safeway().revoke(helper_id):
            return kit.redirect("/safeway", "Disconnected that helper. Its token no longer works.")
        return kit.redirect("/safeway", "That helper was already disconnected.")

    @router.post("/safeway/products/search")
    async def search_words(request: Request) -> Response:
        _, form = await kit.checked(request)
        name = str(form.get("name", ""))
        if safeway().product(name) is None:
            return kit.redirect("/safeway", "That item isn't remembered.")
        words = str(form.get("words", ""))
        safeway().set_search_words(name, words)
        if words.strip():
            return kit.redirect(
                "/safeway", f"Next time, the helper searches for “{words.strip()}”."
            )
        return kit.redirect("/safeway", "Next time, the helper searches for the item's name.")

    @router.post("/safeway/products/forget")
    async def forget(request: Request) -> Response:
        _, form = await kit.checked(request)
        name = str(form.get("name", ""))
        if safeway().forget(name):
            return kit.redirect("/safeway", "Forgotten. The helper will pick it again next time.")
        return kit.redirect("/safeway", "That item isn't remembered.")

    # ----- the helper's API -------------------------------------------------------------

    def helper(request: Request) -> Helper | None:
        auth = request.headers.get("Authorization", "")
        scheme, _, token = auth.partition(" ")
        return safeway().helper_for(token.strip()) if scheme.lower() == "bearer" else None

    def refused() -> JSONResponse:
        return JSONResponse({"error": "not connected"}, status_code=401)

    async def body(request: Request) -> Any:
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise InvalidResults("too long")
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise InvalidResults("not JSON") from exc

    @router.post("/api/safeway/claim")
    def claim(request: Request) -> Response:
        found = helper(request)
        if found is None:
            return refused()
        job = safeway().claim(found)
        if job is None:
            return Response(status_code=204)
        return JSONResponse({"job": job})

    @router.post("/api/safeway/jobs/{job_id}/results")
    async def results(request: Request, job_id: int) -> Response:
        found = helper(request)
        if found is None:
            return refused()
        try:
            await safeway().finish(job_id, found, await body(request))
        except InvalidResults as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"ok": True})

    @router.get("/api/safeway/products")
    def products(request: Request) -> Response:
        if helper(request) is None:
            return refused()
        return JSONResponse(
            {
                "products": [
                    {
                        "name": p.name,
                        "search": p.search_words,
                        "product": (
                            {"id": p.product_id, "name": p.product_name, "size": p.size or ""}
                            if p.product_id
                            else None
                        ),
                    }
                    for p in safeway().products()
                ]
            }
        )

    @router.put("/api/safeway/products")
    async def set_product(request: Request) -> Response:
        if helper(request) is None:
            return refused()
        try:
            data = await body(request)
            if not isinstance(data, dict) or not isinstance(data.get("name"), str):
                raise InvalidResults("a product needs the item's name")
            safeway().remember(data["name"], check_product(data.get("product")))
        except InvalidResults as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"ok": True})

    return router
