"""A local fake of the Google Sheets (v4) API, enough for expense sheets (EX4a, EX4b).

    fake_gsheets.values(sid, "Business")     # [[cell text, ...], ...] as the tab reads now
    fake_gsheets.colour(sid, "Business", 1, 2)  # (r, g, b) or None
    fake_gsheets.note(sid, "Business", 1, 2)
    fake_gsheets.delete(sid)                 # deleted in Google
    fake_gsheets.delete_tab(sid, "Mileage")
    fake_gsheets.fail("batchUpdate", 429)

It holds cells (value, note, background colour) by row and column, hidden columns, and tab
order. drive.file: only the address whose token made a spreadsheet can open it (anyone
else gets a 404, as Google answers for a file Themi can't see).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from itertools import count
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from tests.fakes._server import BackgroundServer
from tests.fakes.google_oauth import FakeGoogle
from themi_google.connectors.google import GoogleConfig


@dataclass
class _Cell:
    value: str | float = ""
    note: str = ""
    colour: tuple[float, float, float] | None = None


@dataclass
class _Tab:
    id: int
    title: str
    rows: list[list[_Cell]] = field(default_factory=list)
    hidden: set[int] = field(default_factory=set)


@dataclass
class _Spreadsheet:
    title: str
    owner: str
    tabs: list[_Tab] = field(default_factory=list)


class FakeGsheets:
    def __init__(self, google: FakeGoogle) -> None:
        self.google = google
        self._lock = threading.Lock()
        self._ids = count(1)
        self.spreadsheets: dict[str, _Spreadsheet] = {}
        self.failures: dict[str, list[int]] = {}
        self.calls: list[tuple[str, str]] = []  # (endpoint, spreadsheet id)
        self.app = FastAPI()
        self.app.add_api_route("/v4/spreadsheets", self._create, methods=["POST"])
        self.app.add_api_route("/v4/spreadsheets/{sid}", self._get, methods=["GET"])
        self.app.add_api_route("/v4/spreadsheets/{sid}:batchUpdate", self._batch, methods=["POST"])
        self.app.add_api_route(
            "/v4/spreadsheets/{sid}/values/{cells}", self._values, methods=["GET"]
        )
        self._background = BackgroundServer(self.app)

    @property
    def url(self) -> str:
        return self._background.url

    def config(self, base: GoogleConfig | None = None) -> GoogleConfig:
        return replace(base or self.google.config(), sheets_url=self.url)

    def start(self) -> None:
        self._background.start()

    def stop(self) -> None:
        self._background.stop()

    def reset(self) -> None:
        with self._lock:
            self.spreadsheets, self.failures, self.calls = {}, {}, []

    # ----- looking and scripting ------------------------------------------------------

    def tab(self, sid: str, title: str) -> _Tab:
        return next(t for t in self.spreadsheets[sid].tabs if t.title == title)

    def titles(self, sid: str) -> list[str]:
        return [t.title for t in self.spreadsheets[sid].tabs]

    def values(self, sid: str, title: str, *, shown: bool = False) -> list[list[Any]]:
        """The tab's values, row by row (`shown`: without its hidden columns)."""
        tab = self.tab(sid, title)
        return [
            [c.value for n, c in enumerate(row) if not (shown and n in tab.hidden)]
            for row in tab.rows
        ]

    def colour(self, sid: str, title: str, row: int, column: int) -> tuple[float, ...] | None:
        return self.tab(sid, title).rows[row][column].colour

    def note(self, sid: str, title: str, row: int, column: int) -> str:
        return self.tab(sid, title).rows[row][column].note

    def delete(self, sid: str) -> None:
        with self._lock:
            del self.spreadsheets[sid]

    def delete_tab(self, sid: str, title: str) -> None:
        with self._lock:
            sheet = self.spreadsheets[sid]
            sheet.tabs = [t for t in sheet.tabs if t.title != title]

    def fail(self, endpoint: str, status: int, *, times: int = 1) -> None:
        self.failures.setdefault(endpoint, []).extend([status] * times)

    # ----- the API --------------------------------------------------------------------

    def _who(self, request: Request, endpoint: str, sid: str) -> tuple[str | None, Response | None]:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        address = self.google.state.access_tokens.get(token)
        self.calls.append((endpoint, sid))
        if address is None:
            return None, JSONResponse({"error": {"code": 401}}, status_code=401)
        queued = self.failures.get(endpoint)
        if queued:
            status = queued.pop(0)
            return None, JSONResponse({"error": {"code": status}}, status_code=status)
        return address.lower(), None

    def _open(
        self, request: Request, endpoint: str, sid: str
    ) -> tuple[_Spreadsheet | None, Response]:
        address, refused = self._who(request, endpoint, sid)
        if refused is not None:
            return None, refused
        sheet = self.spreadsheets.get(sid)
        if sheet is None or sheet.owner != address:
            return None, JSONResponse({"error": {"code": 404}}, status_code=404)
        return sheet, Response()

    def _render(self, sid: str, sheet: _Spreadsheet) -> dict[str, Any]:
        return {
            "spreadsheetId": sid,
            "properties": {"title": sheet.title},
            "sheets": [
                {"properties": {"sheetId": t.id, "title": t.title, "index": n}}
                for n, t in enumerate(sheet.tabs)
            ],
        }

    async def _create(self, request: Request) -> Response:
        address, refused = self._who(request, "create", "")
        if refused is not None:
            return refused
        body = await request.json()
        with self._lock:
            sid = f"sheet-{next(self._ids)}"
            tabs = [
                _Tab(next(self._ids), s["properties"]["title"]) for s in body.get("sheets") or []
            ] or [_Tab(0, "Sheet1")]
            self.spreadsheets[sid] = _Spreadsheet(body["properties"]["title"], str(address), tabs)
            return JSONResponse(self._render(sid, self.spreadsheets[sid]))

    async def _get(self, request: Request, sid: str) -> Response:
        sheet, refused = self._open(request, "get", sid)
        if sheet is None:
            return refused
        return JSONResponse(self._render(sid, sheet))

    async def _values(self, request: Request, sid: str, cells: str) -> Response:
        sheet, refused = self._open(request, "values", sid)
        if sheet is None:
            return refused
        title = unquote(cells).rsplit("!", 1)[0].strip("'").replace("''", "'")
        tab = next((t for t in sheet.tabs if t.title == title), None)
        if tab is None:
            return JSONResponse({"error": {"code": 400}}, status_code=400)
        column = [[row[0].value] if row and row[0].value != "" else [] for row in tab.rows]
        while column and not column[-1]:
            column.pop()
        return JSONResponse({"values": column})

    async def _batch(self, request: Request, sid: str) -> Response:
        sheet, refused = self._open(request, "batchUpdate", sid)
        if sheet is None:
            return refused
        body = await request.json()
        replies = []
        with self._lock:
            for change in body.get("requests") or []:
                replies.append(self._apply(sheet, change))
        return JSONResponse({"spreadsheetId": sid, "replies": replies})

    def _by_id(self, sheet: _Spreadsheet, tab_id: int) -> _Tab:
        return next(t for t in sheet.tabs if t.id == tab_id)

    def _apply(self, sheet: _Spreadsheet, change: dict[str, Any]) -> dict[str, Any]:
        ((kind, body),) = change.items()
        if kind == "addSheet":
            p = body["properties"]
            tab = _Tab(next(self._ids), p["title"])
            sheet.tabs.insert(min(int(p.get("index", len(sheet.tabs))), len(sheet.tabs)), tab)
            return {"addSheet": {"properties": {"sheetId": tab.id, "title": tab.title}}}
        if kind == "updateSheetProperties":
            p = body["properties"]
            tab = self._by_id(sheet, p["sheetId"])
            fields = body["fields"].split(",")
            if "title" in fields:
                tab.title = p["title"]
            if "index" in fields:
                sheet.tabs.remove(tab)
                sheet.tabs.insert(min(int(p["index"]), len(sheet.tabs)), tab)
            return {}
        if kind == "deleteSheet":
            sheet.tabs = [t for t in sheet.tabs if t.id != body["sheetId"]]
            return {}
        if kind == "updateDimensionProperties":
            r = body["range"]
            tab = self._by_id(sheet, r["sheetId"])
            if r["dimension"] == "COLUMNS" and body["properties"].get("hiddenByUser"):
                tab.hidden.update(range(r["startIndex"], r["endIndex"]))
            return {}
        if kind == "deleteDimension":
            r = body["range"]
            tab = self._by_id(sheet, r["sheetId"])
            del tab.rows[r["startIndex"] : r["endIndex"]]
            return {}
        if kind == "updateCells":
            start = body["start"]
            tab = self._by_id(sheet, start["sheetId"])
            for n, row in enumerate(body["rows"]):
                self._write(tab, start["rowIndex"] + n, start.get("columnIndex", 0), row)
            return {}
        if kind == "appendCells":
            tab = self._by_id(sheet, body["sheetId"])
            last = max((n for n, row in enumerate(tab.rows) if any(c.value != "" for c in row)),
                       default=-1)  # fmt: skip
            for n, row in enumerate(body["rows"]):
                self._write(tab, last + 1 + n, 0, row)
            return {}
        raise AssertionError(f"the fake Sheets API doesn't know {kind}")

    def _write(self, tab: _Tab, row: int, column: int, data: dict[str, Any]) -> None:
        while len(tab.rows) <= row:
            tab.rows.append([])
        cells = tab.rows[row]
        values = data.get("values") or []
        while len(cells) < column + len(values):
            cells.append(_Cell())
        for n, value in enumerate(values):
            entered = value.get("userEnteredValue") or {}
            colour = (value.get("userEnteredFormat") or {}).get("backgroundColor")
            cells[column + n] = _Cell(
                entered.get("numberValue", entered.get("stringValue", "")),
                value.get("note", ""),
                (colour["red"], colour["green"], colour["blue"]) if colour else None,
            )


@pytest.fixture(scope="session")
def _fake_gsheets_server(_fake_google_server: FakeGoogle) -> Iterator[FakeGsheets]:
    server = FakeGsheets(_fake_google_server)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_gsheets(_fake_gsheets_server: FakeGsheets, fake_google: FakeGoogle) -> FakeGsheets:
    _fake_gsheets_server.reset()
    return _fake_gsheets_server
