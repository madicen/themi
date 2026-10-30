"""A local fake of the Google Tasks API (v1): the inbox (GT1a) and Themi's own list (GT1b).

    fake_gtasks.add("erin@gmail.com", "Buy milk")          # said to a speaker: My Tasks
    fake_gtasks.add("erin@gmail.com", "Plumber", due="2026-10-23T00:00:00.000Z")
    fake_gtasks.titles("erin@gmail.com")                  # what's left in My Tasks
    fake_gtasks.titles("erin@gmail.com", "Themi")         # what's on the Themi list
    fake_gtasks.complete("erin@gmail.com", "Themi", "Call the vet")  # done in Google
    fake_gtasks.fail("delete", 503)

Requests are authorised with access tokens from the fake Google. Each address has its
own lists; "@default" is its "My Tasks", as in Google.
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

DEFAULT = "My Tasks"


def _now() -> str:
    return clock.now().astimezone(UTC).isoformat().replace("+00:00", "Z")


class FakeGtasks:
    def __init__(self, google: FakeGoogle) -> None:
        self.google = google
        self._lock = threading.Lock()
        self._ids = count(1)
        # address -> list id -> {"title": ..., "tasks": {task id: task}}
        self.accounts: dict[str, dict[str, dict[str, Any]]] = {}
        self.failures: dict[str, list[int]] = {}
        self.calls: list[tuple[str, str]] = []  # (endpoint, address)
        self.page_size = 100
        self.app = FastAPI()
        self.app.add_api_route("/tasks/v1/users/@me/lists", self._lists, methods=["GET"])
        self.app.add_api_route("/tasks/v1/users/@me/lists", self._make_list, methods=["POST"])
        base = "/tasks/v1/lists/{lid}/tasks"
        self.app.add_api_route(base, self._list, methods=["GET"])
        self.app.add_api_route(base, self._insert, methods=["POST"])
        self.app.add_api_route(f"{base}/{{tid}}", self._patch, methods=["PATCH"])
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
            self.accounts, self.failures, self.calls = {}, {}, []
            self.page_size = 100

    # ----- scripting ----------------------------------------------------------

    def add(
        self,
        address: str,
        title: str,
        *,
        notes: str = "",
        due: str = "",
        done: bool = False,
        list_title: str = DEFAULT,
    ) -> str:
        task_id = f"t{next(self._ids)}"
        task: dict[str, Any] = {
            "id": task_id,
            "title": title,
            "status": "completed" if done else "needsAction",
            "updated": _now(),
        }
        if notes:
            task["notes"] = notes
        if due:
            task["due"] = due
        self._named(address, list_title)["tasks"][task_id] = task
        return task_id

    def titles(self, address: str, list_title: str = DEFAULT, *, done: bool = False) -> list[str]:
        """Open tasks on that list (or done ones, with `done`)."""
        tasks = self._named(address, list_title)["tasks"].values()
        return [t["title"] for t in tasks if (t["status"] == "completed") == done]

    def task(self, address: str, list_title: str, title: str) -> dict[str, Any]:
        return next(
            t for t in self._named(address, list_title)["tasks"].values() if t["title"] == title
        )

    def complete(self, address: str, list_title: str, title: str) -> None:
        """Ticked in Google's own app: completed, and hidden from a plain list."""
        self.task(address, list_title, title).update(status="completed", hidden=True)

    def has_list(self, address: str, title: str) -> bool:
        return any(lst["title"] == title for lst in self._box(address).values())

    def fail(self, endpoint: str, status: int, *, times: int = 1) -> None:
        """Endpoints: lists, make_list, list, insert, patch, delete."""
        self.failures.setdefault(endpoint, []).extend([status] * times)

    # ----- plumbing -----------------------------------------------------------

    def _box(self, address: str) -> dict[str, dict[str, Any]]:
        box = self.accounts.setdefault(address.lower(), {})
        box.setdefault("default", {"title": DEFAULT, "tasks": {}})
        return box

    def _named(self, address: str, title: str) -> dict[str, Any]:
        box = self._box(address)
        for lst in box.values():
            if lst["title"] == title:
                return lst
        list_id = f"l{next(self._ids)}"
        box[list_id] = {"title": title, "tasks": {}}
        return box[list_id]

    def _open(self, request: Request, endpoint: str) -> tuple[str | None, Response | None]:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        address = self.google.state.access_tokens.get(token)
        self.calls.append((endpoint, address or "?"))
        if address is None:
            return None, JSONResponse({"error": {"code": 401}}, status_code=401)
        queued = self.failures.get(endpoint)
        if queued:
            return None, JSONResponse({"error": {"code": queued[0]}}, status_code=queued.pop(0))
        return address.lower(), None

    def _list_for(self, address: str, lid: str) -> dict[str, Any] | None:
        return self._box(address).get("default" if lid == "@default" else lid)

    async def _lists(self, request: Request) -> Response:
        address, error = self._open(request, "lists")
        if address is None:
            return error  # type: ignore[return-value]
        items = [{"id": lid, "title": lst["title"]} for lid, lst in self._box(address).items()]
        return JSONResponse({"kind": "tasks#taskLists", "items": items})

    async def _make_list(self, request: Request) -> Response:
        address, error = self._open(request, "make_list")
        if address is None:
            return error  # type: ignore[return-value]
        title = (await request.json())["title"]
        list_id = f"l{next(self._ids)}"
        self._box(address)[list_id] = {"title": title, "tasks": {}}
        return JSONResponse({"id": list_id, "title": title})

    async def _list(self, request: Request, lid: str) -> Response:
        address, error = self._open(request, "list")
        if address is None:
            return error  # type: ignore[return-value]
        lst = self._list_for(address, lid)
        if lst is None:
            return JSONResponse({"error": {"code": 404}}, status_code=404)
        params = request.query_params
        done_too = params.get("showCompleted", "true") == "true"
        hidden_too = params.get("showHidden") == "true"
        items = [
            t
            for t in lst["tasks"].values()
            if (done_too or t["status"] != "completed") and (hidden_too or not t.get("hidden"))
        ]
        start = int(params.get("pageToken") or 0)
        page = items[start : start + self.page_size]
        body: dict[str, Any] = {"kind": "tasks#tasks", "items": page}
        if start + self.page_size < len(items):
            body["nextPageToken"] = str(start + self.page_size)
        return JSONResponse(body)

    async def _insert(self, request: Request, lid: str) -> Response:
        address, error = self._open(request, "insert")
        if address is None:
            return error  # type: ignore[return-value]
        lst = self._list_for(address, lid)
        if lst is None:
            return JSONResponse({"error": {"code": 404}}, status_code=404)
        body = await request.json()
        task_id = f"t{next(self._ids)}"
        lst["tasks"][task_id] = {
            "id": task_id,
            "status": "needsAction",
            "updated": _now(),
            **body,
        }
        return JSONResponse(lst["tasks"][task_id])

    async def _patch(self, request: Request, lid: str, tid: str) -> Response:
        address, error = self._open(request, "patch")
        if address is None:
            return error  # type: ignore[return-value]
        lst = self._list_for(address, lid)
        task = lst["tasks"].get(tid) if lst else None
        if task is None:
            return JSONResponse({"error": {"code": 404}}, status_code=404)
        task.update(await request.json())
        task["updated"] = _now()
        return JSONResponse(task)

    async def _delete(self, request: Request, lid: str, tid: str) -> Response:
        address, error = self._open(request, "delete")
        if address is None:
            return error  # type: ignore[return-value]
        lst = self._list_for(address, lid)
        with self._lock:
            if lst is None or lst["tasks"].pop(tid, None) is None:
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
