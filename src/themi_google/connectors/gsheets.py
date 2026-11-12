"""A small Google Sheets (v4) client over `httpx` (EX4a), for expense sheets.

Only what Themi's copy of a sheet needs: make a spreadsheet, add, rename, reorder and delete
its tabs (`addSheet`, `updateSheetProperties`, `deleteSheet`), write a header, add rows and
update the rows found by a hidden id column (column A), set background colours and cell
notes. Changes go as one `batchUpdate` where they can.

The scope is `drive.file`: Themi can open only the spreadsheets it made. Themi's database
is the truth and this is a copy: Themi writes its own columns and leaves any others alone.

Like the other Google clients, a 401 drops the cached access token and retries once. Being
told to slow down (429, 503) raises `SheetsRateLimited` with Google's wait, and the caller
backs off (as the Gmail client's callers do): the client itself never waits.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from themi.http import tls
from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

TIMEOUT = 30.0
ID_COLUMN = 0  # column A holds each row's entry id, hidden

TokenSource = Callable[[], Awaitable[Secret]]
Colour = tuple[float, float, float]


class SheetsError(Exception):
    """Something to tell the person, in plain words."""


class SheetsAuthError(SheetsError):
    pass


class SheetsNotFound(SheetsError):
    """The spreadsheet is gone (deleted in Google), or isn't one Themi made."""


class SheetsRateLimited(SheetsError):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("Google Sheets asked Themi to slow down")
        self.retry_after = retry_after


@dataclass(frozen=True)
class Tab:
    id: int
    title: str
    index: int


@dataclass(frozen=True)
class Cell:
    """One cell as Themi writes it: a value (text or a number), a note, a background."""

    value: str | float | int | None = None
    note: str = ""
    colour: Colour | None = None


# ----- requests, as Google's batchUpdate spells them ----------------------------------------


def add_sheet(title: str, index: int) -> dict[str, Any]:
    return {"addSheet": {"properties": {"title": title, "index": index}}}


def update_sheet(tab_id: int, *, title: str | None = None, index: int | None = None) -> dict:
    properties: dict[str, Any] = {"sheetId": tab_id}
    fields = []
    if title is not None:
        properties["title"] = title
        fields.append("title")
    if index is not None:
        properties["index"] = index
        fields.append("index")
    return {"updateSheetProperties": {"properties": properties, "fields": ",".join(fields)}}


def delete_sheet(tab_id: int) -> dict[str, Any]:
    return {"deleteSheet": {"sheetId": tab_id}}


def hide_column(tab_id: int, column: int = ID_COLUMN) -> dict[str, Any]:
    return {
        "updateDimensionProperties": {
            "range": {"sheetId": tab_id, "dimension": "COLUMNS", "startIndex": column,
                      "endIndex": column + 1},
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser",
        }
    }  # fmt: skip


def delete_row(tab_id: int, row: int) -> dict[str, Any]:
    return {
        "deleteDimension": {
            "range": {"sheetId": tab_id, "dimension": "ROWS", "startIndex": row,
                      "endIndex": row + 1}
        }
    }  # fmt: skip


def _cell(cell: Cell) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if isinstance(cell.value, int | float) and not isinstance(cell.value, bool):
        data["userEnteredValue"] = {"numberValue": cell.value}
    else:
        data["userEnteredValue"] = {"stringValue": "" if cell.value is None else str(cell.value)}
    data["note"] = cell.note
    if cell.colour is not None:
        red, green, blue = cell.colour
        data["userEnteredFormat"] = {"backgroundColor": {"red": red, "green": green, "blue": blue}}
    else:
        data["userEnteredFormat"] = {}
    return data


CELL_FIELDS = "userEnteredValue,note,userEnteredFormat.backgroundColor"


def update_cells(tab_id: int, row: int, cells: Sequence[Cell], column: int = 0) -> dict:
    return {
        "updateCells": {
            "start": {"sheetId": tab_id, "rowIndex": row, "columnIndex": column},
            "rows": [{"values": [_cell(c) for c in cells]}],
            "fields": CELL_FIELDS,
        }
    }


def append_cells(tab_id: int, rows: Sequence[Sequence[Cell]]) -> dict[str, Any]:
    return {
        "appendCells": {
            "sheetId": tab_id,
            "rows": [{"values": [_cell(c) for c in row]} for row in rows],
            "fields": CELL_FIELDS,
        }
    }


def upsert_requests(
    tab_id: int,
    header: Sequence[str],
    rows: Mapping[str, Sequence[Cell]],
    existing: Sequence[str],
    *,
    remove: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """The requests that bring a tab in line: the header on row 1 (its id column empty), each
    row found by its id in `existing` (column A as it reads now) updated in place, the others
    added at the end, and the rows of `remove` taken out (last first, so the others stay
    where they are). A row's cells start with its id."""
    requests = [
        update_cells(tab_id, 0, [Cell(""), *(Cell(h) for h in header)]),
        hide_column(tab_id),
    ]
    where = {key: n for n, key in enumerate(existing) if key and n > 0}
    new = []
    for key, cells in rows.items():
        line = [Cell(key), *cells]
        if key in where:
            requests.append(update_cells(tab_id, where[key], line))
        else:
            new.append(line)
    if new:
        requests.append(append_cells(tab_id, new))
    for row in sorted((where[k] for k in remove if k in where), reverse=True):
        requests.append(delete_row(tab_id, row))
    return requests


class SheetsClient:
    def __init__(self, sheets_url: str, token: TokenSource, on_unauthorized: Callable[[], None]):
        self.base = f"{sheets_url.rstrip('/')}/v4/spreadsheets"
        self.token = token
        self.on_unauthorized = on_unauthorized

    async def create(self, title: str, tabs: Sequence[str]) -> tuple[str, list[Tab]]:
        """A new spreadsheet with these tabs, in order. Returns its id and its tabs."""
        body = {
            "properties": {"title": title},
            "sheets": [{"properties": {"title": t, "index": n}} for n, t in enumerate(tabs)],
        }
        made = await self._request("POST", self.base, json=body)
        return str(made["spreadsheetId"]), _tabs(made)

    async def tabs(self, spreadsheet_id: str) -> list[Tab]:
        """Its tabs as they are now; SheetsNotFound when it's gone."""
        got = await self._request(
            "GET",
            f"{self.base}/{quote(spreadsheet_id, safe='')}",
            params={"fields": "spreadsheetId,properties.title,sheets.properties"},
        )
        return _tabs(got)

    async def batch(self, spreadsheet_id: str, requests: Sequence[dict[str, Any]]) -> list[dict]:
        """Apply `requests` in one go. Returns Google's replies, one a request."""
        if not requests:
            return []
        done = await self._request(
            "POST",
            f"{self.base}/{quote(spreadsheet_id, safe='')}:batchUpdate",
            json={"requests": list(requests)},
        )
        return list(done.get("replies") or [])

    async def add_tab(self, spreadsheet_id: str, title: str, index: int) -> int:
        (reply,) = await self.batch(spreadsheet_id, [add_sheet(title, index)])
        return int(reply["addSheet"]["properties"]["sheetId"])

    async def ids(self, spreadsheet_id: str, tab_title: str) -> list[str]:
        """Column A of a tab: each row's id ('' for the header and for rows Themi didn't
        write)."""
        cells = f"'{tab_title.replace(chr(39), chr(39) * 2)}'!A:A"
        got = await self._request(
            "GET", f"{self.base}/{quote(spreadsheet_id, safe='')}/values/{quote(cells, safe='')}"
        )
        return [str(row[0]) if row else "" for row in got.get("values") or []]

    async def upsert(
        self,
        spreadsheet_id: str,
        tab: Tab,
        header: Sequence[str],
        rows: Mapping[str, Sequence[Cell]],
        *,
        remove: Sequence[str] = (),
    ) -> None:
        """Write the header and these rows (updated where their id is, added if not), and
        take out the rows of `remove`, in one batch."""
        existing = await self.ids(spreadsheet_id, tab.title)
        await self.batch(
            spreadsheet_id, upsert_requests(tab.id, header, rows, existing, remove=remove)
        )

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in (1, 2):
            token = await self.token()
            try:
                async with httpx.AsyncClient(verify=tls(), timeout=TIMEOUT) as client:
                    response = await client.request(
                        method, url, headers={"Authorization": f"Bearer {token.reveal()}"}, **kwargs
                    )
            except httpx.HTTPError as exc:
                raise SheetsError(
                    f"Google Sheets couldn't be reached ({type(exc).__name__})"
                ) from exc
            if response.status_code == 401 and attempt == 1:
                self.on_unauthorized()
                continue
            return _result(response)
        raise AssertionError("unreachable")


def _tabs(spreadsheet: dict[str, Any]) -> list[Tab]:
    found = []
    for sheet in spreadsheet.get("sheets") or []:
        p = sheet.get("properties") or {}
        found.append(Tab(int(p.get("sheetId", 0)), str(p.get("title", "")), int(p.get("index", 0))))
    return sorted(found, key=lambda t: t.index)


def _result(response: httpx.Response) -> dict[str, Any]:
    status = response.status_code
    if status == 200:
        return response.json() if response.content else {}
    if status == 401:
        raise SheetsAuthError("Google refused the access token for Google Sheets")
    if status in (403, 404):
        raise SheetsNotFound("That spreadsheet is gone, or isn't one Themi made.")
    if status in (429, 503):
        retry = response.headers.get("Retry-After")
        raise SheetsRateLimited(
            float(retry) if retry and retry.replace(".", "", 1).isdigit() else None
        )
    log.info("Google Sheets returned HTTP %s for %s", status, response.request.url.path)
    raise SheetsError(f"Google Sheets returned HTTP {status}")
