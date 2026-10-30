"""A local fake of the Google Tasks API (v1), enough for the inbox (GT1a).

    fake_gtasks.add("erin@gmail.com", "Buy milk")          # said to a speaker
    fake_gtasks.add("erin@gmail.com", "Plumber", due="2026-10-23T00:00:00.000Z")
    fake_gtasks.titles("erin@gmail.com")                  # what's left in My Tasks
    fake_gtasks.fail("delete", 503)

Requests are authorised with access tokens from the fake Google. Each address
has its own default list ("@default"), as in Google.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC
from itertools import count
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from tests.fakes._server import BackgroundServer
from tests.fakes.google_oauth import FakeGoogle
from themi import clock
from themi.connectors.google import GoogleConfig


class FakeGtasks:
    def __init__(self, google: FakeGoogle) -> None:
        self.google = google
        self._lock = threading.Lock()
        self._ids = count(1)
        self.tasks: dict[str, dict[str, dict[str, Any]]] = {}  # address -> id -> task
        self.failures: dict[str, list[int]] = {}
        self.calls: list[tuple[str, str]] = []  # (endpoint, address)
        self.page_size = 100
        self.app = FastAPI()
        base = "/tasks/v1/lists/{lid}/tasks"
        self.app.add_api_route(base, self._list, methods=["GET"])
        self.app.add_api_route(f"{base}/{{tid}}", self._delete, methods=["DELETE"])
        self._background = BackgroundServer(self.app)

    @property
    def url(self) -> str:
        return self._background.url

    def config(self, base: GoogleConfig | None = None) -> GoogleConfig:
        return replace(base or self.google.config(), tasks_url=self.url)

    def start(self) -> None:
        self._background.start()

    def stop(self) -> None:
        self._background.stop()

    def reset(self) -> None:
        with self._lock:
            self.tasks, self.failures, self.calls = {}, {}, []
            self.page_size = 100

    # ----- scripting ----------------------------------------------------------

    def add(
        self, address: str, title: str, *, notes: str = "", due: str = "", done: bool = False
    ) -> str:
        task_id = f"t{next(self._ids)}"
        task: dict[str, Any] = {
            "id": task_id,
            "title": title,
            "status": "completed" if done else "needsAction",
            "updated": clock.now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        if notes:
            task["notes"] = notes
        if due:
            task["due"] = due
        self.tasks.setdefault(address.lower(), {})[task_id] = task
        return task_id

    def titles(self, address: str) -> list[str]:
        return [t["title"] for t in self.tasks.get(address.lower(), {}).values()]

    def fail(self, endpoint: str, status: int, *, times: int = 1) -> None:
        """Endpoints: list, delete."""
        self.failures.setdefault(endpoint, []).extend([status] * times)

    # ----- plumbing -----------------------------------------------------------

    def _open(
        self, request: Request, endpoint: str, lid: str
    ) -> tuple[str | None, Response | None]:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        address = self.google.state.access_tokens.get(token)
        self.calls.append((endpoint, address or "?"))
        if address is None:
            return None, JSONResponse({"error": {"code": 401}}, status_code=401)
        if lid != "@default":
            return None, JSONResponse({"error": {"code": 404}}, status_code=404)
        queued = self.failures.get(endpoint)
        if queued:
            return None, JSONResponse({"error": {"code": queued[0]}}, status_code=queued.pop(0))
        return address.lower(), None

    async def _list(self, request: Request, lid: str) -> Response:
        address, error = self._open(request, "list", lid)
        if address is None:
            return error  # type: ignore[return-value]
        params = request.query_params
        assert params.get("showCompleted") == "false"
        items = [t for t in self.tasks.get(address, {}).values() if t["status"] != "completed"]
        start = int(params.get("pageToken") or 0)
        page = items[start : start + self.page_size]
        body: dict[str, Any] = {"kind": "tasks#tasks", "items": page}
        if start + self.page_size < len(items):
            body["nextPageToken"] = str(start + self.page_size)
        return JSONResponse(body)

    async def _delete(self, request: Request, lid: str, tid: str) -> Response:
        address, error = self._open(request, "delete", lid)
        if address is None:
            return error  # type: ignore[return-value]
        with self._lock:
            if self.tasks.get(address, {}).pop(tid, None) is None:
                return JSONResponse({"error": {"code": 404}}, status_code=404)
        return Response(status_code=204)


@pytest.fixture(scope="session")
def _fake_gtasks_server(_fake_google_server: FakeGoogle) -> Iterator[FakeGtasks]:
    server = FakeGtasks(_fake_google_server)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_gtasks(_fake_gtasks_server: FakeGtasks, fake_google: FakeGoogle) -> FakeGtasks:
    _fake_gtasks_server.reset()
    return _fake_gtasks_server
