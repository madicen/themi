"""A local fake of the Gmail API (v1), enough for Themi's sync and executors.

    gid = fake_gmail.deliver("erin@gmail.com", sender="Bank <alerts@bank.example>",
                             subject="Statement ready", text="Your statement...")
    fake_gmail.expire_history("erin@gmail.com")      # next history.list returns 404
    fake_gmail.fail("history", 429, retry_after=120)

Each address has its own mailbox. Requests are authorised with access tokens
issued by the fake Google, so the token flow is the real one: an unknown or
revoked token gets a 401. History ids grow with every change, `history.list`
filters by history type and label, and paging uses page tokens.
`newer_than:Nd` is the only search operator understood.
"""

from __future__ import annotations

import base64
import re
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta
from email import message_from_bytes
from itertools import count
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tests.fakes._server import BackgroundServer
from tests.fakes.google_oauth import FakeGoogle
from themi import clock
from themi.connectors.gmail.parse import TABS
from themi.connectors.google import GoogleConfig


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


@dataclass
class _Message:
    id: str
    thread_id: str
    labels: list[str]
    internal_ms: int
    payload: dict[str, Any]
    snippet: str


@dataclass
class _Mailbox:
    messages: dict[str, _Message] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)  # {id, type, message, labels}
    history_id: int = 1000
    oldest_history: int = 0  # starts below this are "too old" (404)
    labels: dict[str, str] = field(default_factory=dict)  # user label id -> name
    sent: list[dict[str, Any]] = field(default_factory=list)
    # The category labels this account shows as tabs; the rest show in Primary (Gmail labels
    # by category either way). All four by default.
    tabs: set[str] = field(default_factory=lambda: set(TABS))


@dataclass
class _Failure:
    status: int
    retry_after: int | None


class FakeGmail:
    def __init__(self, google: FakeGoogle) -> None:
        self.google = google
        self._lock = threading.Lock()
        self._ids = count(1)
        self.mailboxes: dict[str, _Mailbox] = {}
        self.failures: dict[str, list[_Failure]] = {}
        self.calls: list[tuple[str, str]] = []  # (endpoint, address)
        self.list_queries: list[str] = []  # each list call's search, in order
        self.app = FastAPI()
        base = "/gmail/v1/users/me"
        self.app.add_api_route(f"{base}/profile", self._profile, methods=["GET"])
        self.app.add_api_route(f"{base}/messages", self._list, methods=["GET"])
        self.app.add_api_route(f"{base}/messages/send", self._send, methods=["POST"])
        self.app.add_api_route(f"{base}/messages/{{mid}}", self._get, methods=["GET"])
        self.app.add_api_route(f"{base}/messages/{{mid}}/modify", self._modify, methods=["POST"])
        self.app.add_api_route(f"{base}/history", self._history, methods=["GET"])
        self.app.add_api_route(f"{base}/labels", self._labels, methods=["GET"])
        self.app.add_api_route(f"{base}/labels", self._create_label, methods=["POST"])
        self._background = BackgroundServer(self.app)

    @property
    def url(self) -> str:
        return self._background.url

    def config(self) -> GoogleConfig:
        """The fake Google's config, with Gmail pointed here."""
        return replace(self.google.config(), gmail_url=self.url)

    def start(self) -> None:
        self._background.start()

    def stop(self) -> None:
        self._background.stop()

    def reset(self) -> None:
        with self._lock:
            self.mailboxes = {}
            self.failures = {}
            self.calls = []
            self.list_queries = []

    # ----- scripting ----------------------------------------------------------

    def mailbox(self, address: str) -> _Mailbox:
        return self.mailboxes.setdefault(address.lower(), _Mailbox())

    def deliver(
        self,
        address: str,
        *,
        sender: str,
        subject: str,
        text: str | None = None,
        html: str | None = None,
        attachments: tuple[tuple[str, str, int], ...] = (),
        labels: tuple[str, ...] = ("INBOX", "UNREAD"),
        age: timedelta = timedelta(0),
        thread_id: str | None = None,
    ) -> str:
        """Mail arrives in `address`'s mailbox. Returns its Gmail id."""
        with self._lock:
            box = self.mailbox(address)
            number = next(self._ids)
            gid = f"m{number:05d}"
            headers = [
                {"name": "From", "value": sender},
                {"name": "To", "value": address},
                {"name": "Subject", "value": subject},
                {"name": "Message-ID", "value": f"<{gid}@mail.example>"},
            ]
            bodies = []
            if text is not None:
                bodies.append(
                    {"mimeType": "text/plain", "body": {"data": _b64(text), "size": len(text)}}
                )
            if html is not None:
                bodies.append(
                    {"mimeType": "text/html", "body": {"data": _b64(html), "size": len(html)}}
                )
            body_part: dict[str, Any] = (
                bodies[0]
                if len(bodies) == 1
                else {"mimeType": "multipart/alternative", "parts": bodies}
            )
            parts = [body_part] + [
                {
                    "mimeType": mime,
                    "filename": name,
                    "body": {"attachmentId": f"a{gid}{i}", "size": size},
                }
                for i, (name, mime, size) in enumerate(attachments)
            ]
            payload = (
                {**body_part, "headers": headers}
                if len(parts) == 1
                else {"mimeType": "multipart/mixed", "headers": headers, "parts": parts}
            )
            moment = clock.now() - age
            box.messages[gid] = _Message(
                gid,
                thread_id or f"t{number:05d}",
                list(labels),
                int(moment.timestamp() * 1000),
                payload,
                (text or re.sub(r"<[^>]+>", " ", html or ""))[:100].strip(),
            )
            self._record(box, "messageAdded", gid, list(labels))
            return gid

    def expire_history(self, address: str) -> None:
        """History before now is forgotten: older start ids get a 404."""
        box = self.mailbox(address)
        box.oldest_history = box.history_id + 1

    def fail(
        self, endpoint: str, status: int, *, times: int = 1, retry_after: int | None = None
    ) -> None:
        """The next `times` calls to `endpoint` fail.

        Endpoints: profile, list, get, history, modify, send, labels.
        """
        self.failures.setdefault(endpoint, []).extend([_Failure(status, retry_after)] * times)

    def calls_to(self, endpoint: str) -> int:
        return sum(1 for e, _ in self.calls if e == endpoint)

    # ----- plumbing -----------------------------------------------------------

    def _record(
        self,
        box: _Mailbox,
        kind: str,
        gid: str,
        labels: list[str],
        changed: Sequence[str] = (),
    ) -> None:
        """`changed`: the labels a labelAdded or labelRemoved record is about."""
        box.history_id += 1
        box.history.append(
            {"id": box.history_id, "type": kind, "message": gid, "labels": labels,
             "changed": list(changed)}
        )  # fmt: skip

    def by_hand(
        self, address: str, gid: str, *, remove: Sequence[str] = (), delete: bool = False
    ) -> None:
        """The person changes a message in Gmail itself: archives it (remove INBOX), reads it
        (remove UNREAD), or deletes it."""
        box = self.mailbox(address)
        message = box.messages[gid]
        if delete:
            del box.messages[gid]
            self._record(box, "messageDeleted", gid, [])
            return
        gone = [label for label in remove if label in message.labels]
        for label in gone:
            message.labels.remove(label)
        self._record(box, "labelRemoved", gid, list(message.labels), gone)

    def _open(self, request: Request, endpoint: str) -> tuple[_Mailbox | None, JSONResponse | None]:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        address = self.google.state.access_tokens.get(token)
        self.calls.append((endpoint, address or "?"))
        if address is None:
            return None, _error(401, "UNAUTHENTICATED", "Invalid Credentials")
        queued = self.failures.get(endpoint)
        if queued:
            failure = queued.pop(0)
            headers = {"Retry-After": str(failure.retry_after)} if failure.retry_after else {}
            response = _error(failure.status, "SCRIPTED", f"scripted {failure.status}")
            response.headers.update(headers)
            return None, response
        return self.mailbox(address), None

    def _resource(self, m: _Message, box: _Mailbox) -> dict[str, Any]:
        return {
            "id": m.id,
            "threadId": m.thread_id,
            "labelIds": m.labels,
            "snippet": m.snippet,
            "historyId": str(box.history_id),
            "internalDate": str(m.internal_ms),
            "payload": m.payload,
        }

    # ----- endpoints ----------------------------------------------------------

    async def _profile(self, request: Request) -> JSONResponse:
        box, error = self._open(request, "profile")
        if box is None:
            return error  # type: ignore[return-value]
        return JSONResponse(
            {
                "emailAddress": "",
                "messagesTotal": len(box.messages),
                "historyId": str(box.history_id),
            }
        )

    async def _list(self, request: Request) -> JSONResponse:
        box, error = self._open(request, "list")
        if box is None:
            return error  # type: ignore[return-value]
        q = request.query_params
        self.list_queries.append(q.get("q", ""))
        found = sorted(box.messages.values(), key=lambda m: m.internal_ms, reverse=True)
        if label := q.get("labelIds"):
            found = [m for m in found if label in m.labels]
        if "in:inbox" in q.get("q", ""):
            found = [m for m in found if "INBOX" in m.labels]
        if "category:primary" in q.get("q", ""):
            found = [m for m in found if not set(m.labels) & box.tabs]
        if match := re.search(r"newer_than:(\d+)d", q.get("q", "")):
            cutoff = (clock.now() - timedelta(days=int(match.group(1)))).timestamp() * 1000
            found = [m for m in found if m.internal_ms >= cutoff]
        start, size = int(q.get("pageToken", 0)), int(q.get("maxResults", 100))
        page = found[start : start + size]
        body: dict[str, Any] = {
            "messages": [{"id": m.id, "threadId": m.thread_id} for m in page],
            "resultSizeEstimate": len(found),
        }
        if start + size < len(found):
            body["nextPageToken"] = str(start + size)
        if not page:
            body.pop("messages")
        return JSONResponse(body)

    async def _get(self, request: Request, mid: str) -> JSONResponse:
        box, error = self._open(request, "get")
        if box is None:
            return error  # type: ignore[return-value]
        message = box.messages.get(mid)
        if message is None:
            return _error(404, "NOT_FOUND", "Requested entity was not found.")
        return JSONResponse(self._resource(message, box))

    async def _history(self, request: Request) -> JSONResponse:
        box, error = self._open(request, "history")
        if box is None:
            return error  # type: ignore[return-value]
        q = request.query_params
        start = int(q["startHistoryId"])
        if start < box.oldest_history:
            return _error(404, "NOT_FOUND", "Requested entity was not found.")
        types = set(q.getlist("historyTypes")) or {"messageAdded"}
        shapes = {"messageAdded": "messagesAdded", "labelRemoved": "labelsRemoved",
                  "labelAdded": "labelsAdded", "messageDeleted": "messagesDeleted"}  # fmt: skip
        label = q.get("labelId")
        records = [
            r
            for r in box.history
            if r["id"] > start and r["type"] in types and (label is None or label in r["labels"])
        ]
        offset, size = int(q.get("pageToken", 0)), int(q.get("maxResults", 100))
        page = records[offset : offset + size]
        body: dict[str, Any] = {
            "history": [
                {
                    "id": str(r["id"]),
                    shapes[r["type"]]: [
                        {
                            "message": {"id": r["message"], "labelIds": r["labels"]},
                            **({"labelIds": r["changed"]} if r["changed"] else {}),
                        }
                    ],
                }
                for r in page
            ],
            "historyId": str(box.history_id),
        }
        if offset + size < len(records):
            body["nextPageToken"] = str(offset + size)
        return JSONResponse(body)

    async def _modify(self, request: Request, mid: str) -> JSONResponse:
        box, error = self._open(request, "modify")
        if box is None:
            return error  # type: ignore[return-value]
        message = box.messages.get(mid)
        if message is None:
            return _error(404, "NOT_FOUND", "Requested entity was not found.")
        change = await request.json()
        removed = [label for label in change.get("removeLabelIds", []) if label in message.labels]
        for label in removed:
            message.labels.remove(label)
        added = [label for label in change.get("addLabelIds", []) if label not in message.labels]
        message.labels.extend(added)
        if removed:
            self._record(box, "labelRemoved", mid, list(message.labels), removed)
        if added:
            self._record(box, "labelAdded", mid, list(message.labels), added)
        return JSONResponse(self._resource(message, box))

    async def _labels(self, request: Request) -> JSONResponse:
        box, error = self._open(request, "labels")
        if box is None:
            return error  # type: ignore[return-value]
        system = [{"id": n, "name": n, "type": "system"} for n in ("INBOX", "UNREAD", "SENT")]
        user = [{"id": i, "name": n, "type": "user"} for i, n in box.labels.items()]
        return JSONResponse({"labels": system + user})

    async def _create_label(self, request: Request) -> JSONResponse:
        box, error = self._open(request, "labels")
        if box is None:
            return error  # type: ignore[return-value]
        name = (await request.json())["name"]
        label_id = f"Label_{len(box.labels) + 1}"
        box.labels[label_id] = name
        return JSONResponse({"id": label_id, "name": name, "type": "user"})

    async def _send(self, request: Request) -> JSONResponse:
        box, error = self._open(request, "send")
        if box is None:
            return error  # type: ignore[return-value]
        body = await request.json()
        raw = base64.urlsafe_b64decode(body["raw"] + "=" * (-len(body["raw"]) % 4))
        parsed = message_from_bytes(raw)
        gid = f"s{next(self._ids):05d}"
        box.sent.append(
            {
                "id": gid,
                "threadId": body.get("threadId"),
                "headers": dict(parsed.items()),
                "body": parsed.get_payload(decode=True).decode().strip(),  # type: ignore[union-attr]
            }
        )
        return JSONResponse({"id": gid, "threadId": body.get("threadId"), "labelIds": ["SENT"]})


def _error(status: int, reason: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": status, "message": message, "status": reason}}, status_code=status
    )


@pytest.fixture(scope="session")
def _fake_gmail_server(_fake_google_server: FakeGoogle) -> Iterator[FakeGmail]:
    server = FakeGmail(_fake_google_server)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_gmail(_fake_gmail_server: FakeGmail, fake_google: FakeGoogle) -> FakeGmail:
    _fake_gmail_server.reset()
    return _fake_gmail_server
