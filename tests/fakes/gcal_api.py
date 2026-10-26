"""A local fake of the Google Calendar API (v3), enough for Themi's event writing.

    fake_gcal.add_calendar("erin@gmail.com", "Themi")   # one the family made by hand
    fake_gcal.fail("insert", 500, times=2)
    fake_gcal.events("erin@gmail.com", "Themi")         # what Cozyla would show

Requests are authorised with access tokens from the fake Google. Each address
has its own calendars. Event ids are checked the way Google checks them
(base32hex, 5 to 1024 characters). As in Google, a deleted event keeps its id:
inserting it again is a 409, and updating it brings it back.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from tests.fakes._server import BackgroundServer
from tests.fakes.google_oauth import FakeGoogle
from themi.connectors.google import GoogleConfig

EVENT_ID = re.compile(r"[a-v0-9]{5,1024}")


@dataclass
class _Calendar:
    id: str
    summary: str
    time_zone: str
    access_role: str = "owner"
    events: dict[str, dict[str, Any]] = field(default_factory=dict)


class FakeGcal:
    def __init__(self, google: FakeGoogle) -> None:
        self.google = google
        self._lock = threading.Lock()
        self._ids = count(1)
        self.calendars: dict[str, dict[str, _Calendar]] = {}  # address -> id -> calendar
        self.failures: dict[str, list[int]] = {}
        self.calls: list[tuple[str, str]] = []  # (endpoint, address)
        self.app = FastAPI()
        base = "/calendar/v3"
        self.app.add_api_route(f"{base}/users/me/calendarList", self._list, methods=["GET"])
        self.app.add_api_route(f"{base}/calendars", self._create_calendar, methods=["POST"])
        events = f"{base}/calendars/{{cid}}/events"
        self.app.add_api_route(events, self._insert, methods=["POST"])
        self.app.add_api_route(events, self._list_events, methods=["GET"])
        self.app.add_api_route(f"{events}/{{eid}}", self._update, methods=["PUT"])
        self.app.add_api_route(f"{events}/{{eid}}", self._delete, methods=["DELETE"])
        self._background = BackgroundServer(self.app)

    @property
    def url(self) -> str:
        return self._background.url

    def config(self, base: GoogleConfig | None = None) -> GoogleConfig:
        return replace(base or self.google.config(), calendar_url=self.url)

    def start(self) -> None:
        self._background.start()

    def stop(self) -> None:
        self._background.stop()

    def reset(self) -> None:
        with self._lock:
            self.calendars = {}
            self.failures = {}
            self.calls = []

    # ----- scripting ----------------------------------------------------------

    def add_calendar(self, address: str, summary: str, access_role: str = "owner") -> str:
        cal_id = f"c{next(self._ids)}@group.calendar.google.com"
        self._box(address)[cal_id] = _Calendar(cal_id, summary, "UTC", access_role)
        return cal_id

    def calendar(self, address: str, summary: str) -> _Calendar | None:
        return next((c for c in self._box(address).values() if c.summary == summary), None)

    def events(self, address: str, summary: str = "Themi") -> list[dict[str, Any]]:
        """The live (not deleted) events on a calendar, by start date."""
        cal = self.calendar(address, summary)
        if cal is None:
            return []
        live = [e for e in cal.events.values() if e.get("status") != "cancelled"]
        return sorted(live, key=lambda e: (e["start"].get("date", ""), e["id"]))

    def add_event(
        self,
        address: str,
        start: str,
        end: str,
        *,
        summary: str = "Something private",
        all_day: bool = False,
        transparency: str = "opaque",
        declined: bool = False,
        status: str = "confirmed",
    ) -> None:
        """An event on someone's primary calendar. `start`/`end`: RFC 3339, or dates."""
        cal = self._box(address).setdefault(
            "primary", _Calendar("primary", address, "UTC", "owner")
        )
        eid = f"e{next(self._ids)}"
        key = "date" if all_day else "dateTime"
        event: dict[str, Any] = {
            "id": eid,
            "summary": summary,
            "start": {key: start},
            "end": {key: end},
            "transparency": transparency,
            "status": status,
        }
        if declined:
            event["attendees"] = [{"email": address, "self": True, "responseStatus": "declined"}]
        cal.events[eid] = event

    def fail(self, endpoint: str, status: int, *, times: int = 1) -> None:
        """The next `times` calls to `endpoint` fail.

        Endpoints: calendarList, create_calendar, insert, update, delete, list_events.
        """
        self.failures.setdefault(endpoint, []).extend([status] * times)

    def calls_to(self, endpoint: str) -> int:
        return sum(1 for e, _ in self.calls if e == endpoint)

    # ----- plumbing -----------------------------------------------------------

    def _box(self, address: str) -> dict[str, _Calendar]:
        return self.calendars.setdefault(address.lower(), {})

    def _open(
        self, request: Request, endpoint: str
    ) -> tuple[dict[str, _Calendar] | None, JSONResponse | None]:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        address = self.google.state.access_tokens.get(token)
        self.calls.append((endpoint, address or "?"))
        if address is None:
            return None, _error(401, "Invalid Credentials")
        queued = self.failures.get(endpoint)
        if queued:
            return None, _error(queued.pop(0), "scripted failure")
        return self._box(address), None

    async def _list(self, request: Request) -> JSONResponse:
        box, error = self._open(request, "calendarList")
        if box is None:
            return error  # type: ignore[return-value]
        items = [
            {"id": c.id, "summary": c.summary, "accessRole": c.access_role} for c in box.values()
        ]
        return JSONResponse({"items": items})

    async def _create_calendar(self, request: Request) -> JSONResponse:
        box, error = self._open(request, "create_calendar")
        if box is None:
            return error  # type: ignore[return-value]
        body = await request.json()
        cal_id = f"c{next(self._ids)}@group.calendar.google.com"
        box[cal_id] = _Calendar(cal_id, body["summary"], body.get("timeZone", "UTC"))
        return JSONResponse({"id": cal_id, "summary": body["summary"]})

    def _calendar(self, box: dict[str, _Calendar], cid: str) -> _Calendar | None:
        cal = box.get(cid)
        return cal if cal is not None and cal.access_role in ("owner", "writer") else None

    async def _insert(self, request: Request, cid: str) -> JSONResponse:
        box, error = self._open(request, "insert")
        if box is None:
            return error  # type: ignore[return-value]
        cal = self._calendar(box, cid)
        if cal is None:
            return _error(404, "Not Found")
        event = await request.json()
        eid = event.get("id") or f"e{next(self._ids)}"
        if not EVENT_ID.fullmatch(eid):
            return _error(400, "Invalid resource id value.")
        if eid in cal.events:
            return _error(409, "The requested identifier already exists.")
        cal.events[eid] = {**event, "id": eid, "status": event.get("status", "confirmed")}
        return JSONResponse(cal.events[eid])

    async def _list_events(self, request: Request, cid: str) -> JSONResponse:
        box, error = self._open(request, "list_events")
        if box is None:
            return error  # type: ignore[return-value]
        cal = box.get(cid)
        if cal is None:
            return JSONResponse({"items": []})
        low = _when(request.query_params.get("timeMin", "1970-01-01T00:00:00Z"))
        high = _when(request.query_params.get("timeMax", "2999-01-01T00:00:00Z"))
        items = [
            e
            for e in cal.events.values()
            if _when(e["end"].get("dateTime") or e["end"]["date"]) > low
            and _when(e["start"].get("dateTime") or e["start"]["date"]) < high
        ]
        return JSONResponse({"items": items})

    async def _update(self, request: Request, cid: str, eid: str) -> JSONResponse:
        box, error = self._open(request, "update")
        if box is None:
            return error  # type: ignore[return-value]
        cal = self._calendar(box, cid)
        if cal is None or eid not in cal.events:
            return _error(404, "Not Found")
        event = await request.json()
        cal.events[eid] = {**event, "id": eid, "status": event.get("status", "confirmed")}
        return JSONResponse(cal.events[eid])

    async def _delete(self, request: Request, cid: str, eid: str) -> Response:
        box, error = self._open(request, "delete")
        if box is None:
            return error  # type: ignore[return-value]
        cal = self._calendar(box, cid)
        if cal is None or eid not in cal.events:
            return _error(404, "Not Found")
        if cal.events[eid].get("status") == "cancelled":
            return _error(410, "Resource has been deleted")
        cal.events[eid]["status"] = "cancelled"
        return Response(status_code=204)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": status, "message": message}}, status_code=status)


@pytest.fixture(scope="session")
def _fake_gcal_server(_fake_google_server: FakeGoogle) -> Iterator[FakeGcal]:
    server = FakeGcal(_fake_google_server)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_gcal(_fake_gcal_server: FakeGcal, fake_google: FakeGoogle) -> FakeGcal:
    _fake_gcal_server.reset()
    return _fake_gcal_server


def _when(value: str) -> datetime:
    """An RFC 3339 time or a plain date (as midnight UTC), for comparing."""
    if len(value) == 10:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
