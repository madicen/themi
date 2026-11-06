"""F26b: which email an approval came from, and its line in a group's message."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from themi.autonomy import Action
from themi.core.approval_groups import _line, email_of

GROUP = {"sender_name": "Jennifer Noble", "sender": "jennifer@noble.example"}


def action(category: str, summary: str = "", **payload: Any) -> Action:
    return Action(
        id=1, category=category, member_id=1, summary=summary, executor="x", payload=payload,
        status="pending", automatic=False, snoozed_until=None, attempts=0, last_error=None,
        result=None, created_at=datetime(2026, 11, 3, tzinfo=UTC),
    )  # fmt: skip


def test_the_email_an_approval_came_from() -> None:
    assert email_of(action("email_mark_read", email_id=984)) == 984
    assert email_of(action("email_reply", email_id=7, body="Hi")) == 7
    assert email_of(action("calendar_from_email", source="email:987")) == 987
    assert email_of(action("calendar_from_email", source="chat")) is None
    assert email_of(action("email_forward", email_id=5)) is None  # asked for in chat
    assert email_of(action("calendar_event")) is None


def test_a_line_leaves_out_who_its_from() -> None:
    summary = (
        "A confirmation to mark as read: Booked (from Jennifer Noble <Jennifer@Noble.example>)"
    )
    assert (
        _line(action("email_mark_read", summary), GROUP) == "A confirmation to mark as read: Booked"
    )
    other = "A confirmation to mark as read: Booked (from Sam <sam@noble.example>)"
    assert _line(action("email_mark_read", other), GROUP) == other  # someone else in the thread


def test_an_events_line_starts_with_the_event() -> None:
    summary = "From an email: tutoring, Mon 16 Nov, 4-5 pm, for your calendar"
    assert _line(action("calendar_from_email", summary), GROUP) == (
        "Tutoring, Mon 16 Nov, 4-5 pm, for your calendar"
    )
