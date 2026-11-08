"""A local fake of the Google Docs (v1) and Drive (v3) APIs, enough for the cookbook (RC1a)
and adding a recipe to it (RC5).

    fake_gdocs.add_doc(DOC_ID, "Madicen Family Cookbook", cookbook(), shared_with=[ERIN])
    fake_gdocs.edit(DOC_ID, lambda doc: ...)   # a person changed the doc: a new revision
    fake_gdocs.paragraphs(DOC_ID)              # [(text, style)] as the doc reads now
    fake_gdocs.fail("get", 503)

A document is a list of blocks: ("P", text, style) paragraphs, ("TABLE", rows) and
("HR",) horizontal rules. Indices are worked out as Google counts them closely enough for
inserting at a paragraph's start or the doc's end, which is all Themi does. `shared_with`
is drive.file: only those addresses' tokens can open it (anyone else gets a 404).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from itertools import count
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from tests.fakes._server import BackgroundServer
from tests.fakes.google_oauth import FakeGoogle
from themi_google.connectors.gdocs import DOC_MIME
from themi_google.connectors.google import GoogleConfig

STYLES = {
    "T": "TITLE",
    "H1": "HEADING_1",
    "H2": "HEADING_2",
    "H3": "HEADING_3",
    "H4": "HEADING_4",
    "H5": "HEADING_5",
    "H6": "HEADING_6",
    "P": "NORMAL_TEXT",
}


@dataclass
class _Para:
    text: str
    style: str = "NORMAL_TEXT"
    heading_id: str = ""
    rule: bool = False


@dataclass
class _Table:
    rows: list[list[str]]


@dataclass
class _Doc:
    title: str
    blocks: list[_Para | _Table]
    shared_with: set[str]
    mime: str = DOC_MIME
    revision: int = 1
    can_edit: bool = True
    requests: list[list[dict[str, Any]]] = field(default_factory=list)


def _length(block: _Para | _Table) -> int:
    if isinstance(block, _Para):
        return 1 if block.rule else len(block.text) + 1
    # table start + per row (1 + per cell (1 + paragraph)) + table end
    return 2 + sum(1 + sum(2 + len(cell) for cell in row) for row in block.rows)


class FakeGdocs:
    def __init__(self, google: FakeGoogle) -> None:
        self.google = google
        self._lock = threading.Lock()
        self._ids = count(1)
        self.docs: dict[str, _Doc] = {}
        self.failures: dict[str, list[int]] = {}
        self.calls: list[tuple[str, str]] = []  # (endpoint, doc id)
        self.edits_before_write = 0  # someone edits just before each of the next N writes
        self.app = FastAPI()
        self.app.add_api_route("/v1/documents/{doc_id}", self._get, methods=["GET"])
        self.app.add_api_route(
            "/v1/documents/{doc_id}:batchUpdate", self._batch_update, methods=["POST"]
        )
        self.app.add_api_route("/drive/v3/files/{doc_id}", self._file, methods=["GET"])
        self._background = BackgroundServer(self.app)

    @property
    def url(self) -> str:
        return self._background.url

    def config(self, base: GoogleConfig | None = None) -> GoogleConfig:
        return replace(base or self.google.config(), docs_url=self.url, drive_url=self.url)

    def start(self) -> None:
        self._background.start()

    def stop(self) -> None:
        self._background.stop()

    def reset(self) -> None:
        with self._lock:
            self.docs, self.failures, self.calls = {}, {}, []
            self.edits_before_write = 0

    # ----- scripting ----------------------------------------------------------

    def add_doc(
        self,
        doc_id: str,
        title: str,
        blocks: list[tuple[Any, ...]],
        *,
        shared_with: list[str] = (),  # type: ignore[assignment]
        mime: str = DOC_MIME,
    ) -> None:
        self.docs[doc_id] = _Doc(
            title, [self._block(b) for b in blocks], {a.lower() for a in shared_with}, mime
        )

    def share(self, doc_id: str, address: str) -> None:
        self.docs[doc_id].shared_with.add(address.lower())

    def edit(self, doc_id: str, change: Callable[[list[_Para | _Table]], None]) -> None:
        """A person edited the doc in Google: `change` gets the block list to alter."""
        doc = self.docs[doc_id]
        change(doc.blocks)
        doc.revision += 1

    def para(self, kind: str, text: str) -> _Para:
        """A block for `edit`: para("H4", "Toast")."""
        return self._block((kind, text))  # type: ignore[return-value]

    def paragraphs(self, doc_id: str) -> list[tuple[str, str]]:
        return [
            (b.text, b.style)
            for b in self.docs[doc_id].blocks
            if isinstance(b, _Para) and not b.rule
        ]

    def fail(self, endpoint: str, status: int, *, times: int = 1) -> None:
        """Endpoints: get, file, batch_update."""
        self.failures.setdefault(endpoint, []).extend([status] * times)

    # ----- plumbing -----------------------------------------------------------

    def _block(self, spec: tuple[Any, ...]) -> _Para | _Table:
        kind = spec[0]
        if kind == "HR":
            return _Para("", rule=True)
        if kind == "TABLE":
            return _Table([list(r) for r in spec[1]])
        style = STYLES[kind]
        return _Para(str(spec[1]), style, self._heading_id(style))

    def _heading_id(self, style: str) -> str:
        return f"h.{next(self._ids):06d}" if style.startswith("HEADING") else ""

    def _open(self, request: Request, endpoint: str, doc_id: str) -> tuple[_Doc | None, Response]:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        address = self.google.state.access_tokens.get(token)
        self.calls.append((endpoint, doc_id))
        if address is None:
            return None, JSONResponse({"error": {"code": 401}}, status_code=401)
        queued = self.failures.get(endpoint)
        if queued:
            status = queued.pop(0)
            return None, JSONResponse({"error": {"code": status}}, status_code=status)
        doc = self.docs.get(doc_id)
        if doc is None or address.lower() not in doc.shared_with:
            return None, JSONResponse({"error": {"code": 404}}, status_code=404)
        return doc, Response()

    def _render(self, doc_id: str, doc: _Doc) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"startIndex": 0, "endIndex": 1, "sectionBreak": {}}]
        index = 1
        for block in doc.blocks:
            length = _length(block)
            start, end = index, index + length
            if isinstance(block, _Table):
                rows = [
                    {
                        "tableCells": [
                            {"content": [{"paragraph": _paragraph(cell, "NORMAL_TEXT", "")}]}
                            for cell in row
                        ]
                    }
                    for row in block.rows
                ]
                content.append({"startIndex": start, "endIndex": end, "table": {"tableRows": rows}})
            elif block.rule:
                content.append(
                    {
                        "startIndex": start,
                        "endIndex": end,
                        "paragraph": {
                            "elements": [{"horizontalRule": {}}, {"textRun": {"content": "\n"}}],
                            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                        },
                    }
                )
            else:
                content.append(
                    {
                        "startIndex": start,
                        "endIndex": end,
                        "paragraph": _paragraph(block.text, block.style, block.heading_id),
                    }
                )
            index = end
        return {
            "documentId": doc_id,
            "title": doc.title,
            "revisionId": f"rev{doc.revision}",
            "body": {"content": content},
        }

    def _starts(self, doc: _Doc) -> list[int]:
        starts, index = [], 1
        for block in doc.blocks:
            starts.append(index)
            index += _length(block)
        starts.append(index)  # the end
        return starts

    async def _get(self, request: Request, doc_id: str) -> Response:
        doc, error = self._open(request, "get", doc_id)
        if doc is None:
            return error
        return JSONResponse(self._render(doc_id, doc))

    async def _file(self, request: Request, doc_id: str) -> Response:
        doc, error = self._open(request, "file", doc_id)
        if doc is None:
            return error
        return JSONResponse(
            {
                "id": doc_id,
                "name": doc.title,
                "mimeType": doc.mime,
                "version": str(doc.revision),
                "modifiedTime": f"2026-11-0{min(doc.revision, 9)}T00:00:00Z",
                "capabilities": {"canEdit": doc.can_edit},
            }
        )

    async def _batch_update(self, request: Request, doc_id: str) -> Response:
        doc, error = self._open(request, "batch_update", doc_id)
        if doc is None:
            return error
        body = await request.json()
        if self.edits_before_write:
            self.edits_before_write -= 1
            doc.revision += 1  # a person typed in the doc between Themi's read and write
        wanted = body.get("writeControl", {}).get("requiredRevisionId")
        if wanted is not None and wanted != f"rev{doc.revision}":
            return JSONResponse(
                {
                    "error": {
                        "code": 400,
                        "message": f"The required revision ID {wanted} does not match",
                    }
                },
                status_code=400,
            )
        with self._lock:
            for item in body.get("requests", []):
                if "insertText" in item:
                    if not self._insert(doc, item["insertText"]):
                        return JSONResponse({"error": {"code": 400}}, status_code=400)
                elif "updateParagraphStyle" in item:
                    self._style(doc, item["updateParagraphStyle"])
            doc.requests.append(body.get("requests", []))
            doc.revision += 1
        return JSONResponse(
            {"documentId": doc_id, "writeControl": {"requiredRevisionId": f"rev{doc.revision}"}}
        )

    def _insert(self, doc: _Doc, request: dict[str, Any]) -> bool:
        index = int(request["location"]["index"])
        lines = str(request["text"]).split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        starts = self._starts(doc)
        if index in starts[:-1]:
            at = starts.index(index)
            block = doc.blocks[at]
            inherited = block.style if isinstance(block, _Para) else "NORMAL_TEXT"
        elif index >= starts[-1] - 1:
            at, inherited = len(doc.blocks), "NORMAL_TEXT"
        else:
            return False
        doc.blocks[at:at] = [_Para(line, inherited) for line in lines]
        return True

    def _style(self, doc: _Doc, request: dict[str, Any]) -> None:
        low, high = int(request["range"]["startIndex"]), int(request["range"]["endIndex"])
        style = str(request["paragraphStyle"]["namedStyleType"])
        for block, start in zip(doc.blocks, self._starts(doc), strict=False):
            if isinstance(block, _Para) and low <= start < high:
                block.style = style
                if style.startswith("HEADING") and not block.heading_id:
                    block.heading_id = self._heading_id(style)
                elif not style.startswith("HEADING"):
                    block.heading_id = ""


def _paragraph(text: str, style: str, heading_id: str) -> dict[str, Any]:
    paragraph_style: dict[str, Any] = {"namedStyleType": style}
    if heading_id:
        paragraph_style["headingId"] = heading_id
    return {"elements": [{"textRun": {"content": f"{text}\n"}}], "paragraphStyle": paragraph_style}


@pytest.fixture(scope="session")
def _fake_gdocs_server(_fake_google_server: FakeGoogle) -> Iterator[FakeGdocs]:
    server = FakeGdocs(_fake_google_server)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_gdocs(_fake_gdocs_server: FakeGdocs, fake_google: FakeGoogle) -> FakeGdocs:
    _fake_gdocs_server.reset()
    return _fake_gdocs_server
