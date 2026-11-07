"""F34o: a bug report with a screenshot. The screenshot is kept with the report, encrypted
with the key kept outside the database, and deleted once it's reviewed or after 60 days."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from tests.scenarios.harness import Scenario
from themi import clock
from themi.channels.events import Picture
from themi.cli import main
from themi.core.feedback import MAX_PICTURES, FeedbackBook
from themi.storage import open_database
from themi.storage.secrets import Cipher, generate_key

SCREENSHOT = b"PNG: Themi's message, cut off after 'and then'"


def book(scenario: Scenario) -> FeedbackBook:
    feedback = scenario.app.services.feedback
    assert feedback is not None
    return feedback.book


def kept(scenario: Scenario) -> list[bytes]:
    return [k.data for k in book(scenario).pictures([r["id"] for r in reports(scenario)])]


def reports(scenario: Scenario) -> list:
    return scenario.app.db.query("SELECT id, kind, text FROM feedback ORDER BY id")


async def test_bug_in_a_caption_keeps_the_screenshot_encrypted(scenario: Scenario) -> None:
    """The scenario: a screenshot of a cut-off message with "/bug the end is missing"."""
    (reply,) = await scenario.picture("Erin", SCREENSHOT, caption="/bug the end is missing")
    assert "Your screenshot is saved with it." in reply
    assert kept(scenario) == [SCREENSHOT]
    (row,) = scenario.app.db.query("SELECT data, mime_type FROM feedback_pictures")
    assert SCREENSHOT not in bytes(row["data"]) and row["mime_type"] == "image/jpeg"
    report = book(scenario).report(book(scenario).items())
    assert "**Screenshots:** 1 sent with it" in report


async def test_thats_a_bug_after_a_picture_keeps_that_picture(scenario: Scenario) -> None:
    scenario.primary.queue_text("It's a message from me, cut off.")
    await scenario.picture("Erin", SCREENSHOT, caption="what happened here?")
    scenario.primary.queue_tool_call("log_feedback", {"kind": "bug", "summary": "message cut off"})
    scenario.primary.queue_text("Noted, with your screenshot.")
    await scenario.say("Erin", "that's a bug, it got cut off")
    assert kept(scenario) == [SCREENSHOT]


async def test_a_picture_sent_with_plain_words_about_a_bug(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("log_feedback", {"kind": "bug", "summary": "cut off"})
    scenario.primary.queue_text("Noted.")
    await scenario.picture("Erin", SCREENSHOT, caption="this is broken")
    assert kept(scenario) == [SCREENSHOT]
    result = scenario.primary.last_request.messages[-1].content[0]
    assert "screenshot is saved" in str(result)


async def test_a_report_about_something_else_doesnt_take_the_picture(scenario: Scenario) -> None:
    scenario.primary.queue_text("A flyer.")
    await scenario.picture("Erin", SCREENSHOT, caption="what's this?")
    await scenario.say("Erin", "/bug the reminder came late yesterday")
    assert len(reports(scenario)) == 1 and kept(scenario) == []


async def test_a_picture_with_no_report_isnt_kept(scenario: Scenario) -> None:
    scenario.primary.queue_text("A flyer.")
    await scenario.picture("Erin", SCREENSHOT, caption="what's this?")
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM feedback_pictures") == 0


async def test_reviewed_reports_and_old_pictures_are_deleted(scenario: Scenario) -> None:
    await scenario.picture("Erin", SCREENSHOT, caption="/bug the end is missing")
    await scenario.picture("Erin", SCREENSHOT + b"2", caption="/idea show a preview")
    first, second = (r["id"] for r in reports(scenario))
    book(scenario).mark_reviewed([first])
    assert [k.feedback_id for k in book(scenario).pictures([first, second])] == [second]
    clock.advance(timedelta(days=59))
    assert await scenario.run_periodic("feedback.forget_pictures") == 0
    clock.advance(timedelta(days=2))
    assert await scenario.run_periodic("feedback.forget_pictures") == 1
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM feedback_pictures") == 0


async def test_at_most_three_pictures_a_report(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    feedback = scenario.app.services.feedback
    assert feedback is not None
    pictures = [Picture(f"PNG {n}".encode(), "image/png") for n in range(5)]
    item = feedback.record(erin, "bug", "lots", "/bug", pictures=pictures)
    assert len(book(scenario).pictures([item])) == MAX_PICTURES


async def test_removing_the_member_removes_their_pictures(scenario: Scenario) -> None:
    await scenario.picture("Husband", SCREENSHOT, caption="/bug the end is missing")
    husband = scenario.member("Husband")
    scenario.app.db.execute("DELETE FROM members WHERE id = ?", (husband.id,))
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM feedback_pictures") == 0


def test_the_cli_writes_the_screenshots_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    key = generate_key()
    db_path = tmp_path / "data" / "themi.db"
    monkeypatch.setenv("THEMI_SECRET_KEY", key)
    monkeypatch.setenv("THEMI_DB_PATH", str(db_path))
    monkeypatch.chdir(tmp_path)  # no stray .env
    db = open_database(db_path)
    db.execute(
        "INSERT INTO family (id, name, timezone, created_at, updated_at) "
        "VALUES (1, 'Household', 'UTC', '2026-10-21T16:00:00+00:00', '2026-10-21T16:00:00+00:00')"
    )
    member = db.execute(
        "INSERT INTO members (name, role, tracking, created_at, updated_at) "
        "VALUES ('Erin', 'admin', '{}', '2026-10-21T16:00:00+00:00', '2026-10-21T16:00:00+00:00')"
    )
    reports = FeedbackBook(db, Cipher(key))
    item = reports.record(member, "bug", "cut off", {"member": {"name": "Erin"}})
    reports.attach(item, member, [Picture(SCREENSHOT, "image/png")])

    assert main(["feedback", "--pictures", str(tmp_path / "shots")]) == 0
    out = capsys.readouterr()
    assert (tmp_path / "shots" / f"report-{item}-1.png").read_bytes() == SCREENSHOT
    assert f"report-{item}-1.*" in out.out and "Wrote 1 screenshot(s)" in out.err
    assert main(["feedback", "--done", str(item)]) == 0
    assert db.scalar("SELECT COUNT(*) FROM feedback_pictures") == 0
