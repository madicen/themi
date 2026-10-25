"""The feedback store and its Markdown report (the CLI's view of /bug and /idea)."""

from datetime import datetime

from tests.fixtures.family import SeededFamily
from themi.core.feedback import FeedbackBook

CONTEXT = {
    "version": "0.1.0",
    "via": "/bug",
    "local_time": "Wed 21 Oct 2026 09:05 PDT",
    "member": {"id": 1, "name": "Erin", "role": "admin"},
    "replied_to": {"at": "Wed 09:01", "kind": "from Themi chat", "text": "Added king sheets."},
    "conversation": [
        {"at": "Wed 09:00", "direction": "in", "kind": "chat", "text": "we need king sheets"},
        {"at": "Wed 09:01", "direction": "out", "kind": "approval", "text": "King sheets\nOK?"},
    ],
    "open_items": ["Waiting on you: King sheets for the grocery list"],
    "settings": {"quiet hours": "21:30-08:00", "pauses": "none"},
    "ai": [{"label": "Gemini (free tier)", "kind": "gemini", "model": "m", "has_key": True}],
    "log": ["2026-10-21 09:01:00 INFO themi.core.tools: Tool add_to_grocery_list ran"],
}


def test_record_list_and_review(family: SeededFamily, frozen_clock: datetime) -> None:
    book = FeedbackBook(family.db)
    erin = family.erin
    first = book.record(erin.id, "bug", "  it wasn't added  ", CONTEXT)
    second = book.record(erin.id, "idea", "weekly summary", {"member": {"name": "Erin"}})

    items = book.items()
    assert [(i.id, i.kind, i.text, i.status) for i in items] == [
        (first, "bug", "it wasn't added", "new"),
        (second, "idea", "weekly summary", "new"),
    ]
    assert items[0].context == CONTEXT and items[0].created_at == frozen_clock

    assert book.mark_reviewed([first, 999]) == 1
    assert [i.id for i in book.items()] == [second]
    assert [i.status for i in book.items(include_reviewed=True)] == ["reviewed", "new"]
    assert book.mark_reviewed([first]) == 0  # already reviewed
    assert book.mark_reviewed([]) == 0


def test_the_report_has_everything_to_work_from(family: SeededFamily) -> None:
    book = FeedbackBook(family.db)
    erin = family.erin
    item_id = book.record(erin.id, "bug", "it wasn't added\nonly waiting", CONTEXT)
    report = book.report(book.items())

    assert report.startswith("# Themi feedback from the family chat")
    assert "1 bug report(s) and 0 idea(s)" in report
    assert f"## Bug #{item_id} from Erin, Wed 21 Oct 2026 09:05 PDT" in report
    assert "> it wasn't added\n> only waiting" in report
    assert "Sent via /bug. Themi 0.1.0." in report
    assert (
        "**In reply to** this message (Wed 09:01, from Themi chat):\n> Added king sheets." in report
    )
    assert "[Wed 09:00] Erin: we need king sheets" in report
    assert "[Wed 09:01] Themi (approval): King sheets\n    OK?" in report
    assert "- Waiting on you: King sheets for the grocery list" in report
    assert "**Settings:** quiet hours: 21:30-08:00; pauses: none" in report
    assert "Gemini (free tier) (gemini, m, key set)" in report
    assert "Tool add_to_grocery_list ran" in report


def test_an_empty_report(family: SeededFamily) -> None:
    assert FeedbackBook(family.db).report([]) == "No new feedback.\n"
