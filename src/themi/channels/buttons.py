"""Buttons on chat messages, the same on every channel that has them (Telegram's, Slack's).

A button carries only a short random token; what it does (its kind and payload) stays in
`callback_tokens` on the server. One answer per set of buttons: a tap uses them all, unless
they're for anyone in a group (then the handler closes them).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from themi import clock
from themi.accounts import Member
from themi.channels.events import Button
from themi.storage.db import Database

BUTTON_TTL = timedelta(days=7)
# Erin's idea #80: more than a couple of buttons go on several rows, two a row, or three
# when every label is short ("Yes", "No", "Later").
SHORT_LABEL = 8

NOT_YOURS_TEXT = "That one isn't yours to answer."
ALREADY_HANDLED_TEXT = "Already taken care of."


def button_rows(labels: Sequence[str]) -> list[list[int]]:
    """Which buttons (by index) go on each row."""
    if len(labels) <= 2:
        return [list(range(len(labels)))]
    per_row = 3 if all(len(label) <= SHORT_LABEL for label in labels) else 2
    return [list(range(i, min(i + per_row, len(labels)))) for i in range(0, len(labels), per_row)]


def store_tokens(
    db: Database, member: Member, buttons: Sequence[Button], *, anyone: bool = False
) -> tuple[str | None, list[str | None]]:
    """A token for each button (None for a link button, which calls nothing back), all in
    one group. Returns the group's id (None without buttons) and the tokens in order."""
    if not buttons:
        return None, []
    group_id = secrets.token_urlsafe(9)
    now = clock.now()
    tokens: list[str | None] = []
    for button in buttons:
        if button.web_app is not None:
            tokens.append(None)
            continue
        token = secrets.token_urlsafe(12)  # Telegram allows 64 bytes of callback data
        db.execute(
            "INSERT INTO callback_tokens (token, group_id, member_id, label, kind, payload, "
            "created_at, expires_at, anyone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                group_id,
                member.id,
                button.label,
                button.kind,
                json.dumps(button.payload),
                now.isoformat(),
                (now + BUTTON_TTL).isoformat(),
                int(anyone),
            ),
        )
        tokens.append(token)
    return group_id, tokens


def note_message(db: Database, group_id: str | None, message_id: int) -> None:
    """The message the group's buttons are on, once it's sent."""
    if group_id is not None:
        db.execute(
            "UPDATE callback_tokens SET message_id = ? WHERE group_id = ?", (message_id, group_id)
        )


@dataclass(frozen=True)
class Tap:
    """A tap that counts: the button's label, kind and payload, and its message."""

    label: str
    kind: str
    payload: dict[str, Any]
    message_id: int | None
    anyone: bool


def claim(db: Database, token: str, member: Member) -> Tap | Literal["not yours", "handled"]:
    """A tap by `member` on the button with this token: the tap, or why it doesn't count.
    A tap on buttons that aren't for anyone uses up the whole group."""
    row = db.one("SELECT * FROM callback_tokens WHERE token = ?", (token,))
    if row is None:
        return "handled"
    if row["member_id"] != member.id and not row["anyone"]:
        return "not yours"
    if row["used_at"] is not None or datetime.fromisoformat(row["expires_at"]) <= clock.now():
        return "handled"
    if not row["anyone"]:
        db.execute(
            "UPDATE callback_tokens SET used_at = ? WHERE group_id = ? AND used_at IS NULL",
            (clock.now().isoformat(), row["group_id"]),
        )
    return Tap(
        row["label"],
        row["kind"],
        json.loads(row["payload"]),
        row["message_id"],
        bool(row["anyone"]),
    )
