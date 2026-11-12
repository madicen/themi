"""F26b (Erin's idea #137): approvals from one email thread, or one sender a few minutes
apart, in one message."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import FakeGoogle
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link, verdict
from themi.core import keys

JENNIFER = "Jennifer Noble <jennifer@noble.example>"
ICS = (("invite.ics", "text/calendar", 2204),)
TO = "erin@madicen.com"  # not the account Themi reads: Google hasn't added these (F29b)


@pytest.fixture
async def inbox(
    scenario: Scenario,
    fake_google: FakeGoogle,
    fake_gmail: FakeGmail,
    fake_gcal: FakeGcal,
    site: httpx.AsyncClient,
) -> FakeGmail:
    """Erin's inbox and calendar, linked and watched."""
    await link(scenario, site, fake_google, "Erin", ERIN)
    await scenario.tap("Erin", "Watch it")
    await scenario.run_periodic("gmail.poll")
    return fake_gmail


def session(day: str, label: str) -> dict[str, str]:
    return {
        "title": "Tutoring with Malcolm",
        "date": day,
        "start": "16:00",
        "end": "17:00",
        "location": "",
    }


async def arrive(scenario: Scenario, inbox: FakeGmail, mails: list[dict[str, Any]]) -> list[int]:
    before = scenario.app.db.scalar("SELECT COALESCE(MAX(id), 0) FROM emails")
    for mail in mails:
        inbox.deliver(ERIN, **mail)
    await scenario.advance(minutes=3)
    await scenario.run_periodic("gmail.poll")
    rows = scenario.app.db.query("SELECT id FROM emails WHERE id > ? ORDER BY id", (before,))
    return [r["id"] for r in rows]


def invitation(day: str, label: str, thread: str) -> dict[str, Any]:
    return {
        "sender": JENNIFER,
        "subject": f"Invitation: Tutoring with Malcolm @ {label} 4pm - 5pm (PST) ({TO})",
        "text": "You have been invited",
        "attachments": ICS,
        "thread_id": thread,
        "to": TO,
    }


async def burst(scenario: Scenario, inbox: FakeGmail) -> list[int]:
    """3:24 pm: a question to answer and two invitations, weeks away."""
    ids = await arrive(
        scenario,
        inbox,
        [
            {
                "sender": JENNIFER,
                "subject": "Tutoring dates",
                "text": "Do these work?",
                "thread_id": "t-dates",
            },
            invitation("2026-11-09", "Mon Nov 9, 2026", "t-nov9"),
            invitation("2026-11-16", "Mon Nov 16, 2026", "t-nov16"),
        ],
    )
    question, nov9, nov16 = ids
    scenario.primary.queue_structured(
        {
            "results": [
                verdict(question, "needs_reply", reply_draft="Those all work, thank you!"),
                verdict(nov9, "confirmation", event=session("2026-11-09", "9")),
                verdict(nov16, "confirmation", event=session("2026-11-16", "16")),
            ]
        }
    )
    await scenario.run_periodic("email.triage")
    return ids


def cards(scenario: Scenario) -> list[str]:
    """Approval messages Erin got (as sent; later edits aside)."""
    return [
        r["text"]
        for r in scenario.app.db.query(
            "SELECT o.text FROM outbox o JOIN members m ON m.id = o.member_id "
            "WHERE m.name = 'Erin' AND o.kind = 'approval' ORDER BY o.id"
        )
    ]


def statuses(scenario: Scenario) -> list[tuple[str, str, int]]:
    rows = scenario.app.db.query(
        "SELECT category, status, attempts FROM pending_actions ORDER BY id"
    )
    return [(r["category"], r["status"], r["attempts"]) for r in rows]


def buttons(edit: dict[str, Any]) -> list[str]:
    keyboard = edit.get("reply_markup", {}).get("inline_keyboard", [])
    return [b["text"] for row in keyboard for b in row]


BURST = (
    "3 things from Jennifer Noble's emails:\n"
    "- A reply to Jennifer Noble <jennifer@noble.example> about Tutoring dates, from "
    "erin@gmail.com:\n> Those all work, thank you!\n"
    "- Tutoring with Malcolm, Mon 09 Nov, 4-5 pm, for your calendar (an invitation sent to "
    f"{TO})\n"
    "- Tutoring with Malcolm, Mon 16 Nov, 4-5 pm, for your calendar (an invitation sent to "
    f"{TO})\n"
    "Go ahead with all of them, one by one, or not now?"
)


async def test_idea_137s_five_cards_come_as_one_message(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await burst(scenario, inbox)
    assert [c for c, _, _ in statuses(scenario)] == [
        "email_reply",
        "calendar_from_email",
        "email_mark_read",
        "calendar_from_email",
        "email_mark_read",
    ]
    assert len(cards(scenario)) == 1  # five approvals, one message
    assert scenario.edits("Erin")[-1]["text"] == BURST  # "mark as read"s go with their events
    assert buttons(scenario.edits("Erin")[-1]) == [
        "Go ahead with all", "One by one", "Not now", "Not ever",  # F37c: for all of it
    ]  # fmt: skip


async def test_go_ahead_with_all_runs_each_action_once(
    scenario: Scenario, inbox: FakeGmail, fake_gcal: FakeGcal
) -> None:
    await burst(scenario, inbox)
    await scenario.tap("Erin", "Go ahead with all")
    assert [(s, n) for _, s, n in statuses(scenario)] == [("done", 1)] * 5
    assert len(inbox.mailbox(ERIN).sent) == 1
    assert [e["summary"] for e in fake_gcal.events(ERIN, ERIN)] == ["Tutoring with Malcolm"] * 2
    shown = scenario.edits("Erin")[-1]
    assert shown["text"].splitlines()[1].endswith("(done)")
    assert buttons(shown) == []
    # Answered: the buttons are gone, and a tap on an old copy runs nothing again.
    await scenario.tap("Erin", "Go ahead with all")  # an earlier copy of its buttons
    assert [n for _, _, n in statuses(scenario)] == [1] * 5


async def test_one_by_one_sends_the_cards(scenario: Scenario, inbox: FakeGmail) -> None:
    await burst(scenario, inbox)
    await scenario.tap("Erin", "One by one")
    assert scenario.edits("Erin")[-1]["text"].endswith("One at a time, below.")
    singles = cards(scenario)[1:]
    assert [c.splitlines()[-1] for c in singles] == ["Go ahead, or not now?"] * 3
    assert singles[1].startswith("From an email: Tutoring with Malcolm, Mon 09 Nov")
    # Tapping the event's own card marks its email read too.
    await scenario.tap("Erin", "Go ahead")  # the latest card: Mon 16 Nov
    assert [s for _, s, _ in statuses(scenario)][3:] == ["done", "done"]
    assert [s for _, s, _ in statuses(scenario)][:3] == ["pending"] * 3


async def test_not_now_snoozes_them_together(scenario: Scenario, inbox: FakeGmail) -> None:
    await burst(scenario, inbox)
    await scenario.tap("Erin", "Not now")
    assert [s for _, s, _ in statuses(scenario)] == ["snoozed"] * 5
    assert scenario.edits("Erin")[-1]["text"].endswith("No rush, these will come back later.")
    await scenario.advance(hours=3, minutes=5)
    await scenario.run_periodic("approvals.resurface")
    assert len(cards(scenario)) == 2  # back, in one message again
    assert scenario.edits("Erin")[-1]["text"] == BURST


async def test_approvals_from_two_senders_stay_apart(scenario: Scenario, inbox: FakeGmail) -> None:
    first, second = await arrive(
        scenario,
        inbox,
        [
            {"sender": JENNIFER, "subject": "Session booked", "text": "See you"},
            {"sender": "Gabriel <g@tutors.example>", "subject": "Session booked", "text": "Hi"},
        ],
    )
    scenario.primary.queue_structured(
        {"results": [verdict(first, "confirmation"), verdict(second, "confirmation")]}
    )
    await scenario.run_periodic("email.triage")
    assert cards(scenario) == [
        "A confirmation to mark as read: Session booked (from Jennifer Noble "
        "<jennifer@noble.example>)\nGo ahead, or not now?",
        "A confirmation to mark as read: Session booked (from Gabriel <g@tutors.example>)\n"
        "Go ahead, or not now?",
    ]


async def test_a_later_email_in_the_thread_edits_the_waiting_message(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await burst(scenario, inbox)
    await scenario.advance(minutes=57)  # 4:21 pm, a third invitation, in the dates thread
    (later,) = await arrive(
        scenario, inbox, [{**invitation("2026-11-23", "Mon Nov 23, 2026", "t-dates")}]
    )
    scenario.primary.queue_structured(
        {"results": [verdict(later, "confirmation", event=session("2026-11-23", "23"))]}
    )
    await scenario.run_periodic("email.triage")
    assert len(cards(scenario)) == 1  # no new message
    shown = scenario.edits("Erin")[-1]["text"]
    assert shown.startswith("4 things from Jennifer Noble's emails:")
    assert "- Tutoring with Malcolm, Mon 23 Nov, 4-5 pm, for your calendar" in shown


async def test_an_important_later_email_comes_on_its_own(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    """Erin's call (2026-11-05): mail triage rates important (a sender she said is, E2b)
    isn't folded in. (Urgent mail is an alert, never a card.)"""
    await burst(scenario, inbox)
    member, account = (
        scenario.member("Erin"),
        scenario.app.db.scalar("SELECT id FROM linked_accounts WHERE address = ?", (ERIN,)),
    )
    scenario.app.db.execute(
        "INSERT INTO email_audit_items (member_id, account_id, address, label, reason, "
        "created_at, answer, answered_at, urgency, importance) VALUES "
        "(?, ?, 'office@school.example', 'School', '', '', 'important', '', 0, 1)",
        (member.id, account),
    )
    await scenario.advance(minutes=57)
    (later,) = await arrive(
        scenario,
        inbox,
        [
            {
                **invitation("2026-11-23", "Mon Nov 23, 2026", "t-dates"),
                "sender": "School <office@school.example>",
            },
        ],
    )
    scenario.primary.queue_structured(
        {"results": [verdict(later, "confirmation", event=session("2026-11-23", "23"))]}
    )
    await scenario.run_periodic("email.triage")
    new = cards(scenario)[1:]
    assert len(new) == 1 and new[0].startswith("From an email: Tutoring with Malcolm, Mon 23 Nov")
    assert scenario.edits("Erin")[-1]["text"] == BURST  # the waiting message is as it was


async def test_a_yes_in_words_answers_the_whole_message(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await burst(scenario, inbox)
    await scenario.say("Erin", "yes")
    assert [s for _, s, _ in statuses(scenario)] == ["done"] * 5


async def test_a_single_invitation_is_one_card_and_marks_its_email_read(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    (nov9,) = await arrive(scenario, inbox, [invitation("2026-11-09", "Mon Nov 9, 2026", "t9")])
    scenario.primary.queue_structured(
        {"results": [verdict(nov9, "confirmation", event=session("2026-11-09", "9"))]}
    )
    await scenario.run_periodic("email.triage")
    assert cards(scenario) == [
        "From an email: Tutoring with Malcolm, Mon 09 Nov, 4-5 pm, for your calendar (an "
        f"invitation sent to {TO})\nGo ahead, or not now?"
    ]
    await scenario.tap("Erin", "Go ahead")
    assert [s for _, s, _ in statuses(scenario)] == ["done", "done"]
    assert scenario.edits("Erin")[-1]["text"].startswith("From an email: Tutoring")


async def test_someone_else_in_the_thread_joins_it_too(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await burst(scenario, inbox)
    await scenario.advance(minutes=57)
    (later,) = await arrive(
        scenario,
        inbox,
        [
            {
                "sender": "Sam <sam@noble.example>",
                "subject": "Re: Tutoring dates",
                "text": "Got it",
                "thread_id": "t-dates",
            }
        ],
    )
    scenario.primary.queue_structured({"results": [verdict(later, "confirmation")]})
    await scenario.run_periodic("email.triage")
    assert len(cards(scenario)) == 1
    shown = scenario.edits("Erin")[-1]["text"]
    assert shown.startswith("4 things from Jennifer Noble's emails:")
    assert (
        "- A confirmation to mark as read: Re: Tutoring dates (from Sam <sam@noble.example>)"
        in (shown)
    )


# ----- F37c (Michael's idea #188): "these email things need a 'not ever' option" ------------

LASAGNA = "Lasagna Love <lasagnachef@lasagnaloveportal.org>"
RESUME = "From an email: Lasagna Love service resume, Mon 16 Nov 2054, all day, for your calendar"


async def pause(scenario: Scenario, inbox: FakeGmail, day: str = "2054-11-16") -> int:
    """Lasagna Love's "Pause Confirmation", with the day the service resumes."""
    (email,) = await arrive(
        scenario,
        inbox,
        [{"sender": LASAGNA, "subject": "Pause Confirmation",
          "text": f"You have paused your service until {day}."}],
    )  # fmt: skip
    event = {"title": "Lasagna Love service resume", "date": day, "start": "", "end": "",
             "location": ""}  # fmt: skip
    scenario.primary.queue_structured(
        {"results": [verdict(email, "confirmation", "A pause", event=event)]}
    )
    await scenario.run_periodic("email.triage")
    return email


def calendar_statuses(scenario: Scenario) -> list[str]:
    return [s for c, s, _ in statuses(scenario) if c == "calendar_from_email"]


async def test_an_email_calendar_card_has_not_ever_and_says_the_year(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await pause(scenario, inbox)
    assert cards(scenario)[-1] == f"{RESUME}\nGo ahead, or not now?"
    assert scenario.last_buttons("Erin") == ["Go ahead", "Not now", "Not ever"]


async def test_not_ever_then_skip_them_stops_that_senders_calendar_offers(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await pause(scenario, inbox)
    await scenario.tap("Erin", "Not ever")
    assert calendar_statuses(scenario) == ["declined"]
    shown = scenario.edits("Erin")[-1]
    assert shown["text"] == (
        f"{RESUME}\nLeft as is, for good. Skip calendar offers from Lasagna Love from now on?"
    )
    assert buttons(shown) == ["Yes, skip them", "Just this one"]
    await scenario.tap("Erin", "Yes, skip them")
    assert scenario.edits("Erin")[-1]["text"] == (
        f"{RESUME}\nLeft as is. No more calendar offers from Lasagna Love."
    )
    assert buttons(scenario.edits("Erin")[-1]) == []

    await pause(scenario, inbox, "2054-11-23")  # a week later: no calendar card
    assert calendar_statuses(scenario) == ["declined"]
    # Its other mail is triaged as before: the confirmation is still offered to mark read.
    assert [s for c, s, _ in statuses(scenario) if c == "email_mark_read"][-1] == "pending"

    events = scenario.app.services.get(keys.events)
    assert events.skipped(scenario.member("Erin"), "lasagnachef@lasagnaloveportal.org")
    assert not events.skipped(scenario.member("Husband"), "lasagnachef@lasagnaloveportal.org")

    await scenario.advance(hours=3, minutes=5)  # declined for good: it doesn't come back
    await scenario.run_periodic("approvals.resurface")
    assert calendar_statuses(scenario) == ["declined"]


async def test_just_this_one_skips_nothing(scenario: Scenario, inbox: FakeGmail) -> None:
    await pause(scenario, inbox)
    await scenario.tap("Erin", "Not ever")
    await scenario.tap("Erin", "Just this one")
    assert scenario.edits("Erin")[-1]["text"] == f"{RESUME}\nLeft as is, for good."
    await pause(scenario, inbox, "2054-11-23")
    assert calendar_statuses(scenario) == ["declined", "pending"]


async def test_skipped_offers_come_again_when_asked(scenario: Scenario, inbox: FakeGmail) -> None:
    await pause(scenario, inbox)
    await scenario.tap("Erin", "Not ever")
    await scenario.tap("Erin", "Yes, skip them")
    scenario.primary.queue_tool_call("unskip_email_sender", {"sender": "Lasagna Love"})
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", "Show me Lasagna Love's calendar offers again")
    events = scenario.app.services.get(keys.events)
    assert not events.skipped(scenario.member("Erin"), "lasagnachef@lasagnaloveportal.org")
    await pause(scenario, inbox, "2054-11-23")
    assert calendar_statuses(scenario) == ["declined", "pending"]


async def test_a_reply_card_has_two_buttons(scenario: Scenario, inbox: FakeGmail) -> None:
    (email,) = await arrive(
        scenario, inbox, [{"sender": JENNIFER, "subject": "Dates", "text": "Do these work?"}]
    )
    scenario.primary.queue_structured(
        {"results": [verdict(email, "needs_reply", reply_draft="They do, thanks!")]}
    )
    await scenario.run_periodic("email.triage")
    assert scenario.last_buttons("Erin") == ["Go ahead", "Not now"]


async def test_not_ever_on_one_emails_message_is_for_all_of_it(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await burst(scenario, inbox)
    assert buttons(scenario.edits("Erin")[-1])[-1] == "Not ever"
    await scenario.tap("Erin", "Not ever")
    assert [s for _, s, _ in statuses(scenario)] == ["declined"] * 5
    shown = scenario.edits("Erin")[-1]
    assert shown["text"].endswith(
        "\nLeft as is, for good. Skip calendar offers from Jennifer Noble from now on?"
    )
    await scenario.tap("Erin", "Yes, skip them")
    assert scenario.edits("Erin")[-1]["text"].endswith(
        "\nLeft as is. No more calendar offers from Jennifer Noble."
    )


async def test_my_settings_lists_skipped_senders_and_brings_them_back(
    scenario: Scenario, inbox: FakeGmail, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    assert "Skipped senders" not in (await site.get("/settings")).text  # none yet
    await pause(scenario, inbox)
    await scenario.tap("Erin", "Not ever")
    await scenario.tap("Erin", "Yes, skip them")
    page = (await site.get("/settings")).text
    assert "Skipped senders" in page and "Lasagna Love" in page
    field = "unskip_calendar_from_email_lasagnachef@lasagnaloveportal.org"
    assert f'name="{field}"' in page
    saved = await site.post("/settings", data={"csrf": csrf, field: "on"})
    assert saved.status_code == 303
    await pause(scenario, inbox, "2054-11-23")
    assert calendar_statuses(scenario) == ["declined", "pending"]


async def test_a_thumbs_down_on_the_shared_card_declines_all_of_it_and_marks_its_reply(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    """F38c: the 👎 declines every action in F26b's message, as ✅ approves them all."""
    await burst(scenario, inbox)
    db = scenario.app.db
    erin = scenario.member("Erin")
    reply_id = db.execute(
        "INSERT INTO replies (member_id, started_at) VALUES (?, '2026-10-21T16:00:00+00:00')",
        (erin.id,),
    )
    db.execute("UPDATE outbox SET reply_id = ? WHERE kind = 'approval'", (reply_id,))
    await scenario.react("Erin", "👎")
    assert [s for _, s, _ in statuses(scenario)] == ["declined"] * 5
    assert db.scalar("SELECT marked_at FROM replies WHERE id = ?", (reply_id,)) is not None
