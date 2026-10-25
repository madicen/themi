"""Turn a Gmail API message (format=full) into something Themi can read.

- Headers: From (address and name), To and Cc, Subject, Message-ID, References.
- Body: the first text/plain part; failing that, the text/html part with tags,
  scripts and styles stripped. Capped at `MAX_BODY` characters.
- Attachments: listed (name, type, size) but never downloaded.

Everything here is external text. It's stored and later shown to models only
inside a data block (see themi.core.prompts).
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser
from typing import Any

MAX_BODY = 20_000


@dataclass(frozen=True)
class Attachment:
    filename: str
    mime_type: str
    size: int


@dataclass(frozen=True)
class GmailMessage:
    id: str
    thread_id: str
    label_ids: tuple[str, ...]
    from_address: str
    from_name: str
    to: tuple[str, ...]
    subject: str
    snippet: str
    text: str
    attachments: tuple[Attachment, ...]
    received_at: datetime
    message_id_header: str = ""
    references: str = ""


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {h["name"].lower(): h.get("value", "") for h in payload.get("headers", [])}


def _decode(data: str | None, charset: str = "utf-8") -> str:
    if not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (binascii.Error, ValueError):
        return ""
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:  # an unknown charset name
        return raw.decode("utf-8", errors="replace")


def _charset(part: dict[str, Any]) -> str:
    content_type = _headers(part).get("content-type", "")
    match = re.search(r'charset="?([\w.-]+)"?', content_type, re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _walk(part: dict[str, Any]) -> list[dict[str, Any]]:
    parts = [part]
    for child in part.get("parts", []) or []:
        parts.extend(_walk(child))
    return parts


class _TextOnly(HTMLParser):
    BLOCKS = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table", "section"})
    SKIP = frozenset({"script", "style", "head", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skipping += 1
        elif tag in self.BLOCKS:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skipping:
            self._skipping -= 1
        elif tag in self.BLOCKS:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.out.append(data)


def html_to_text(html: str) -> str:
    parser = _TextOnly()
    parser.feed(html)
    parser.close()
    return tidy("".join(parser.out))


def tidy(text: str) -> str:
    lines = [re.sub("[ \t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse_message(message: dict[str, Any]) -> GmailMessage:
    payload = message.get("payload", {})
    headers = _headers(payload)
    name, address = parseaddr(headers.get("from", ""))
    recipients = getaddresses([headers.get("to", ""), headers.get("cc", "")])
    plain = html = ""
    attachments: list[Attachment] = []
    for part in _walk(payload):
        mime = part.get("mimeType", "")
        body = part.get("body", {}) or {}
        if part.get("filename"):
            attachments.append(Attachment(part["filename"], mime, int(body.get("size", 0))))
            continue
        if mime == "text/plain" and not plain:
            plain = _decode(body.get("data"), _charset(part))
        elif mime == "text/html" and not html:
            html = _decode(body.get("data"), _charset(part))
    text = tidy(plain) if plain.strip() else html_to_text(html)
    internal = int(message.get("internalDate", "0") or 0)
    return GmailMessage(
        id=message["id"],
        thread_id=message.get("threadId", message["id"]),
        label_ids=tuple(message.get("labelIds", [])),
        from_address=address.lower(),
        from_name=name,
        to=tuple(a.lower() for _, a in recipients if a),
        subject=headers.get("subject", ""),
        snippet=message.get("snippet", ""),
        text=text[:MAX_BODY],
        attachments=tuple(attachments),
        received_at=datetime.fromtimestamp(internal / 1000, UTC),
        message_id_header=headers.get("message-id", ""),
        references=headers.get("references", ""),
    )
