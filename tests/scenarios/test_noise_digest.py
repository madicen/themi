"""Noise emails in one message (F16b): ideas #61 and #63, bug #66."""

from __future__ import annotations

from datetime import timedelta

import httpx

from tests.fakes.gmail_api import FakeGmail
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, arrive, inbox, verdict
from themi import clock
from themi.accounts.store import SYSTEM

__all__ = ["inbox"]  # the fixture, from triage's scenarios

SALE = {"sender": "Shop <deals@shop.example>", "subject": "20% off", "html": "<p>Sale</p>"}
NEWS = {"sender": "Backerfeed <hello@backerfeed.example>", "subject": "Hobby knife", "text": "."}
DICE = {"sender": "Dice <dice@connect.example>", "subject": "Quick survey", "text": "."}


async def noise(scenario: Scenario, inbox: FakeGmail, *mails: dict) -> list[int]:
    ids = await arrive(scenario, inbox, *mails)
    scenario.primary.queue_structured({"results": [verdict(i, "noise") for i in ids]})
    await scenario.run_periodic("email.triage")
    return ids


async def at(scenario: Scenario, hour: int) -> list[str]:
    """Move the clock to `hour` local time today (or tomorrow if that's past), and run the
    job. Returns what was sent."""
    now = clock.now().astimezone(scenario.app.services.noise._tz())  # type: ignore[union-attr]
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    before = len(scenario.telegram.calls("sendMessage"))
    clock.advance(target - now)
    await scenario.run_periodic("email.noise")
    await scenario.app.outbox.flush()
    return [p["text"] for p in scenario.telegram.calls("sendMessage")[before:]]


def statuses(scenario: Scenario) -> list[str]:
    rows = scenario.app.db.query("SELECT status FROM pending_actions ORDER BY id")
    return [r["status"] for r in rows]


async def test_noise_waits_for_one_message_and_archive_all(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    # Bug #66: ten cards in an afternoon for a limit of 3. Now: none, then one message.
    before = len(scenario.inbox("Erin"))
    await noise(scenario, inbox, SALE, NEWS)
    assert scenario.inbox("Erin")[before:] == []
    (message,) = await at(scenario, 18)
    assert message == (
        "2 emails look like noise:\n"
        "- Shop: 20% off\n"
        "- Backerfeed: Hobby knife\n"
        "Archive them all? You can also pick on the website, under Emails to archive."
    )
    assert scenario.last_buttons("Erin") == ["Archive all", "Not now"]
    await scenario.tap("Erin", "Archive all")
    assert statuses(scenario) == ["done", "done"]
    assert inbox.calls_to("modify") == 2
    assert scenario.edits("Erin")[-1]["text"] == "2 emails look like noise:\nArchived 2."


async def test_mail_already_out_of_the_inbox_is_left_out(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    _, news = await noise(scenario, inbox, SALE, NEWS)
    gid = scenario.app.db.scalar("SELECT gmail_id FROM emails WHERE id = ?", (news,))
    inbox.mailbox(ERIN).messages[gid].labels.remove("INBOX")  # archived by hand
    (message,) = await at(scenario, 18)
    assert message.startswith("One email looks like noise:\n- Shop: 20% off\nArchive it?")
    assert statuses(scenario) == ["pending", "declined"]


async def test_not_now_leaves_them_for_the_next_one(scenario: Scenario, inbox: FakeGmail) -> None:
    await noise(scenario, inbox, SALE)
    await at(scenario, 18)
    await scenario.tap("Erin", "Not now")
    assert scenario.edits("Erin")[-1]["text"].endswith("Left for now. They'll be in the next one.")
    await noise(scenario, inbox, DICE)
    (message,) = await at(scenario, 18)  # the next evening, with the new one too
    assert message.startswith("2 emails look like noise:")


async def test_a_bare_yes_archives_them_all(scenario: Scenario, inbox: FakeGmail) -> None:
    await noise(scenario, inbox, SALE, NEWS)
    await at(scenario, 18)
    scenario.primary.queue_text("unused")
    await scenario.say("Erin", "yes")
    assert statuses(scenario) == ["done", "done"]


async def test_how_often_is_their_setting(scenario: Scenario, inbox: FakeGmail) -> None:
    erin = scenario.member("Erin")
    store = scenario.app.store
    await noise(scenario, inbox, SALE)
    assert await at(scenario, 12) == []  # once a day: 6 pm only
    store.update_settings(SYSTEM, erin.id, noise_emails="twice")
    await noise(scenario, inbox, NEWS)
    (noon,) = await at(scenario, 12)
    assert noon.startswith("2 emails")
    store.update_settings(SYSTEM, erin.id, noise_emails="every_other_day")
    await noise(scenario, inbox, DICE)
    assert await at(scenario, 18) == []  # one went at noon today
    assert await at(scenario, 18) == []  # a day since
    assert await at(scenario, 18) != []  # two days since


async def test_the_daily_limit_holds_it(scenario: Scenario, inbox: FakeGmail) -> None:
    scenario.app.store.update_settings(SYSTEM, scenario.member("Erin").id, daily_limit=0)
    await noise(scenario, inbox, SALE)
    assert await at(scenario, 18) == []
    queued = scenario.app.db.query(
        "SELECT id FROM outbox WHERE kind = 'email' AND status = 'queued'"
    )
    assert len(queued) == 1
    await noise(scenario, inbox, NEWS)
    await at(scenario, 18)  # a newer one replaces the one still waiting
    (row,) = scenario.app.db.query(
        "SELECT text FROM outbox WHERE kind = 'email' AND status = 'queued'"
    )
    assert row["text"].startswith("2 emails")


async def test_the_website_page(
    scenario: Scenario, inbox: FakeGmail, site: httpx.AsyncClient
) -> None:
    await noise(scenario, inbox, SALE, NEWS, DICE)
    csrf = await sign_in(scenario, site, "Erin")
    assert "3 emails that look like noise" in (await site.get("/")).text
    page = (await site.get("/email/noise")).text
    assert "Shop: 20% off" in page and "Archive all 3" in page
    ids = [r["id"] for r in scenario.app.db.query("SELECT id FROM pending_actions ORDER BY id")]
    await site.post("/email/noise", data={"csrf": csrf, "do": "archive", "action": ids[0]})
    await site.post("/email/noise", data={"csrf": csrf, "do": "keep", "action": ids[1]})
    assert statuses(scenario) == ["done", "declined", "pending"]
    await site.post("/email/noise", data={"csrf": csrf, "do": "all"})
    assert statuses(scenario) == ["done", "declined", "done"]
    assert "Nothing to archive" in (await site.get("/email/noise")).text


async def test_his_offers_arent_hers_to_answer(
    scenario: Scenario, inbox: FakeGmail, site: httpx.AsyncClient
) -> None:
    await noise(scenario, inbox, SALE)
    (action_id,) = [r["id"] for r in scenario.app.db.query("SELECT id FROM pending_actions")]
    csrf = await sign_in(scenario, site, "Husband")
    await site.post("/email/noise", data={"csrf": csrf, "do": "archive", "action": action_id})
    assert statuses(scenario) == ["pending"]


async def test_if_gmail_cant_be_reached_theyre_listed_anyway(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await noise(scenario, inbox, SALE)
    inbox.fail("get", 500, times=10)
    (message,) = await at(scenario, 18)
    assert message.startswith("One email looks like noise:")
    assert statuses(scenario) == ["pending"]


PROMO = {**SALE, "labels": ("INBOX", "UNREAD", "CATEGORY_PROMOTIONS")}


async def test_noise_in_a_gmail_tab_isnt_offered(scenario: Scenario, inbox: FakeGmail) -> None:
    # F16d (bug #66): only the Primary inbox counts; Promotions is already out of the way.
    await noise(scenario, inbox, PROMO)
    assert statuses(scenario) == []
    assert await at(scenario, 18) == []


async def test_an_email_moved_to_a_tab_is_left_out(scenario: Scenario, inbox: FakeGmail) -> None:
    _, news = await noise(scenario, inbox, SALE, NEWS)
    gid = scenario.app.db.scalar("SELECT gmail_id FROM emails WHERE id = ?", (news,))
    inbox.mailbox(ERIN).messages[gid].labels.append("CATEGORY_UPDATES")
    (message,) = await at(scenario, 18)
    assert message.startswith("One email looks like noise:\n- Shop: 20% off")
    assert statuses(scenario) == ["pending", "declined"]


async def test_a_held_message_is_made_again_before_it_goes(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    scenario.app.store.update_settings(SYSTEM, scenario.member("Erin").id, daily_limit=0)
    _, news = await noise(scenario, inbox, SALE, NEWS)
    await at(scenario, 18)
    gid = scenario.app.db.scalar("SELECT gmail_id FROM emails WHERE id = ?", (news,))
    inbox.mailbox(ERIN).messages[gid].labels.remove("INBOX")  # archived by hand that evening
    clock.advance(timedelta(minutes=30))
    await scenario.run_periodic("email.noise")
    (row,) = scenario.app.db.query(
        "SELECT text FROM outbox WHERE kind = 'email' AND status = 'queued'"
    )
    assert row["text"].startswith("2 emails")  # not within the hour
    clock.advance(timedelta(minutes=31))
    await scenario.run_periodic("email.noise")
    (row,) = scenario.app.db.query(
        "SELECT text FROM outbox WHERE kind = 'email' AND status = 'queued'"
    )
    assert row["text"].startswith("One email looks like noise:")


async def test_asked_in_chat_the_waiting_ones_are_there_to_archive(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    # Bug #67: "Are there any messages to mark read or archive?" got only the two items
    # waiting on him; the noise offers were in a queued message the model saw cut short.
    scenario.app.store.update_settings(SYSTEM, scenario.member("Erin").id, daily_limit=0)
    await noise(scenario, inbox, SALE, NEWS, DICE)
    await at(scenario, 18)  # held by the daily limit
    scenario.primary.queue_tool_call("archive_noise_emails", {"answer": "archive", "which": []})
    scenario.primary.queue_text("Archived all three.")
    await scenario.say("Erin", "Are there any messages to mark read or archive?")
    first = scenario.primary.requests[-2]
    turn = first.messages[0].text
    assert "Emails that look like noise, 3 waiting for a yes to archive" in turn
    assert '<data source="their inbox">\n- Shop: 20% off\n- Backerfeed: Hobby knife\n' in turn
    assert "archive_noise_emails" in [t.name for t in first.tools]
    assert statuses(scenario) == ["done", "done", "done"]
    assert inbox.calls_to("modify") == 3
    held = scenario.app.db.query("SELECT 1 FROM outbox WHERE kind = 'email' AND status = 'queued'")
    assert held == []  # the held message, with nothing left, is taken back


async def test_some_archived_and_some_kept_from_chat(scenario: Scenario, inbox: FakeGmail) -> None:
    await noise(scenario, inbox, SALE, NEWS, DICE)
    scenario.primary.queue_tool_calls(
        [
            ("archive_noise_emails", {"answer": "keep", "which": ["dice"]}, None),
            ("archive_noise_emails", {"answer": "archive", "which": ["shop", "hobby"]}, None),
        ]
    )
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", "Keep the Dice one, archive the rest")
    assert statuses(scenario) == ["done", "done", "declined"]
    scenario.primary.queue_tool_call("archive_noise_emails", {"answer": "archive", "which": []})
    scenario.primary.queue_text("Nothing left.")
    await scenario.say("Erin", "archive the noise")
    result = scenario.primary.last_request.messages[-1]
    assert "No emails are waiting to be archived as noise." in str(result)


async def test_noise_in_gmails_tabs_is_explained_when_asked(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    # Bug #74: "Archive my email noise please" got "No noise emails are waiting right now";
    # "there definitely are". All 17 overnight were in Promotions and Updates (F16d).
    updates = {**NEWS, "labels": ("INBOX", "UNREAD", "CATEGORY_UPDATES")}
    await noise(scenario, inbox, PROMO, updates)
    scenario.primary.queue_tool_call("archive_noise_emails", {"answer": "archive", "which": []})
    scenario.primary.queue_text("None in Primary.")
    await scenario.say("Erin", "Archive my email noise please")
    result = str(scenario.primary.last_request.messages[-1])
    assert "No emails are waiting to be archived as noise." in result
    assert "2 that look like noise are in Gmail's other tabs" in result
    assert "only the Primary inbox" in result


# ----- idea #83: mail dealt with in Gmail itself ------------------------------------------


def gmail_id(scenario: Scenario, email_id: int) -> str:
    return scenario.app.db.scalar("SELECT gmail_id FROM emails WHERE id = ?", (email_id,))


async def poll(scenario: Scenario) -> None:
    await scenario.advance(minutes=3)
    await scenario.run_periodic("gmail.poll")


def waiting(scenario: Scenario) -> list[str]:
    rows = scenario.app.db.query(
        "SELECT category FROM pending_actions WHERE status IN ('pending', 'snoozed') ORDER BY id"
    )
    return [r["category"] for r in rows]


async def test_mail_archived_in_gmail_leaves_themis_list(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    # Erin's idea #83: "emails that have been marked read or archived by the user will be
    # cleared from Themi's email queue".
    sale, _ = await noise(scenario, inbox, SALE, NEWS)
    inbox.by_hand(ERIN, gmail_id(scenario, sale), remove=["INBOX"])
    await poll(scenario)
    assert waiting(scenario) == ["email_archive_noise"]  # only the one still in the inbox
    labels = scenario.app.db.scalar("SELECT labels FROM emails WHERE id = ?", (sale,))
    assert "INBOX" not in labels
    (message,) = await at(scenario, 18)
    assert message.startswith("One email looks like noise:\n- Backerfeed: Hobby knife")
    assert inbox.calls_to("modify") == 0  # nothing done twice


async def test_mail_read_or_deleted_in_gmail_leaves_it_too(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    confirmation, needs_reply = await arrive(
        scenario,
        inbox,
        {"sender": "Clinic <hi@clinic.example>", "subject": "Booked", "text": "See you"},
        {"sender": "Jenn <jenn@example.com>", "subject": "Tutoring", "text": "Mondays?"},
    )
    scenario.primary.queue_structured(
        {
            "results": [
                verdict(confirmation, "confirmation"),
                verdict(needs_reply, "needs_reply", reply_draft="Mondays work."),
            ]
        }
    )
    await scenario.run_periodic("email.triage")
    assert waiting(scenario) == ["email_mark_read", "email_reply"]

    inbox.by_hand(ERIN, gmail_id(scenario, confirmation), remove=["UNREAD"])
    inbox.by_hand(ERIN, gmail_id(scenario, needs_reply), remove=["UNREAD"])
    await poll(scenario)
    assert waiting(scenario) == ["email_reply"]  # read isn't answered
    inbox.by_hand(ERIN, gmail_id(scenario, needs_reply), delete=True)
    await poll(scenario)
    assert waiting(scenario) == []
    assert scenario.edits("Erin")[-1]["text"].endswith("Taken care of in Gmail already.")


async def test_themis_own_archiving_isnt_mistaken_for_theirs(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await noise(scenario, inbox, SALE, NEWS)
    await at(scenario, 18)
    await scenario.tap("Erin", "Archive all")
    await poll(scenario)  # the history now has Themi's own label changes
    assert statuses(scenario) == ["done", "done"]


# ----- tabs an account doesn't show (Michael, 2026-10-29) ---------------------------------

UPDATES = {**NEWS, "labels": ("INBOX", "UNREAD", "CATEGORY_UPDATES")}


async def test_noise_labelled_updates_counts_when_updates_isnt_a_tab(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    """Michael had ten unread in Primary that Themi never offered: Gmail labels mail
    CATEGORY_UPDATES even with the Updates tab off, and F16d read the label as a tab."""
    inbox.mailbox(ERIN).tabs = {"CATEGORY_PROMOTIONS"}
    await noise(scenario, inbox, PROMO, UPDATES)
    assert waiting(scenario) == ["email_archive_noise"]
    (message,) = await at(scenario, 18)
    assert message.startswith("One email looks like noise:\n- Backerfeed: Hobby knife")


async def test_noise_skipped_before_the_tabs_were_known_is_offered_then(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await noise(scenario, inbox, PROMO, UPDATES)
    assert waiting(scenario) == []  # Updates is a tab here, so far
    inbox.mailbox(ERIN).tabs = {"CATEGORY_PROMOTIONS"}  # turned off in Gmail's settings
    await scenario.advance(minutes=24 * 60)
    await scenario.run_periodic("gmail.poll")
    assert waiting(scenario) == ["email_archive_noise"]
    rows = scenario.app.db.query("SELECT summary FROM pending_actions")
    assert [r["summary"] for r in rows] == [
        "Probably noise, to archive: Hobby knife (from Backerfeed <hello@backerfeed.example>)"
    ]
