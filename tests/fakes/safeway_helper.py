"""A fake Safeway helper (the Chrome extension, 35d) talking to Themi's /api/safeway/."""

from __future__ import annotations

from typing import Any

import httpx


class FakeSafewayHelper:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.token = token
        self.jobs: list[dict[str, Any]] = []

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def claim(self) -> httpx.Response:
        response = await self.client.post("/api/safeway/claim", headers=self.headers)
        if response.status_code == 200:
            self.jobs.append(response.json()["job"])
        return response

    async def answer(self, job_id: int, body: Any) -> httpx.Response:
        return await self.client.post(
            f"/api/safeway/jobs/{job_id}/results", headers=self.headers, json=body
        )

    async def fill(self, outcomes: dict[str, str] | None = None) -> httpx.Response:
        """Claim the next job and answer it: every item added (a made-up product unless
        one was remembered), except those `outcomes` says otherwise."""
        claimed = await self.claim()
        assert claimed.status_code == 200, claimed.status_code
        job = self.jobs[-1]
        lines = []
        for n, item in enumerate(job["items"]):
            status = (outcomes or {}).get(item["name"], "added")
            product = item["product"] or {
                "id": str(970000000 + n),
                "name": f"{item['search'].title()} - 1 Each",
                "size": "1 Each",
                "price": 3.99,
            }
            lines.append(
                {
                    "name": item["name"],
                    "status": status,
                    "qty": item["qty"],
                    "product": product if status in ("added", "out_of_stock") else None,
                }
            )
        return await self.answer(job["id"], {"items": lines, "stopped": False})
