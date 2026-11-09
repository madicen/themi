"""SL6: Themi writes Michael's Slack status and Do Not Disturb from its own state: focus
time, meetings, quiet hours. It never reads them back, and leaves his own alone."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from tests.fakes.slack_api import MICHAEL, FakeSlack
from tests.fixtures.family import SeededFamily
from tests.scenarios.slack_harness import SlackScenario
from themi import clock
from themi.accounts import SYSTEM, Member
from themi.localtime import to_utc_iso
from themi.standard.slack import SlackModule
from themi.standard.slack_status import SlackStatus
from themi.storage.secrets import Secret


async def started(family: SeededFamily, slack: FakeSlack, *, sync: bool = True) -> SlackScenario:
    scenario = SlackScenario(family, slack, [SlackModule()], status_sync=sync)
    await scenario.start()
    family.store.set_identity(family.erin.id, "slack", MICHAEL)
    return scenario


def erin(scenario: SlackScenario) -> Member:
    return scenario.app.store.get_member(scenario.family.erin.id)


def account(scenario: SlackScenario) -> int:
    found = scenario.app.db.scalar(
        "SELECT id FROM linked_accounts WHERE address = 'erin@work.test'"
    )
    if found is not None:
        return int(found)
    linked = scenario.app.store.add_linked_account(
        SYSTEM, erin(scenario).id, "gmail", "erin@work.test", Secret("refresh")
    )
    return linked.id


def a_task_block(scenario: SlackScenario, minutes: int) -> datetime:
    """A block Themi put on the calendar for a task, from now; when it ends."""
    db, now = scenario.app.db, clock.now()
    ends = now + timedelta(minutes=minutes)
    task = db.execute(
        "INSERT INTO tasks (title, kind, effort, assign_reason, created_at) "
        "VALUES ('Write the deck', 'text', 2, 'theirs', ?)",
        (to_utc_iso(now),),
    )
    event = db.execute(
        "INSERT INTO themi_events (member_id, account_id, calendar_id, event_id, title, "
        "starts_at, ends_at, source, created_at) VALUES (?, ?, 'primary', 'ev-block', "
        "'Write the deck', ?, ?, 'task_block', ?)",
        (erin(scenario).id, account(scenario), to_utc_iso(now), to_utc_iso(ends), to_utc_iso(now)),
    )
    db.execute(
        "INSERT INTO task_blocks (task_id, member_id, themi_event_id, starts_at, ends_at, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (task, erin(scenario).id, event, to_utc_iso(now), to_utc_iso(ends), to_utc_iso(now)),
    )
    return ends


def a_meeting(scenario: SlackScenario, minutes: int, *, guests: int = 2) -> int:
    now = clock.now()
    return scenario.app.db.execute(
        "INSERT INTO calendar_entries (member_id, account_id, calendar_id, event_id, title, "
        "starts_at, ends_at, busy, guests, fetched_at) VALUES (?, ?, 'primary', 'ev-1', "
        "'Planning', ?, ?, 1, ?, ?)",
        (erin(scenario).id, account(scenario), to_utc_iso(now),
         to_utc_iso(now + timedelta(minutes=minutes)), guests, to_utc_iso(now)),
    )  # fmt: skip


async def tick(scenario: SlackScenario) -> object:
    return await scenario.app.services.get(SlackStatus).tick()


def status_calls(slack: FakeSlack) -> list[dict]:
    return slack.calls("users.profile.set")


async def test_focus_time_shows_focusing_and_holds_notifications_until_it_ends(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    scenario = await started(family, fake_slack)
    try:
        ends = a_task_block(scenario, 50)
        assert await tick(scenario) == 1
        [status] = status_calls(fake_slack)
        assert status["profile"] == {"status_text": "Focusing", "status_emoji": ":dart:",
                                     "status_expiration": int(ends.timestamp())}  # fmt: skip
        assert [c["num_minutes"] for c in fake_slack.calls("dnd.setSnooze")] == ["50"]
        assert await tick(scenario) == 0  # nothing changed: Slack isn't written again
        clock.advance(timedelta(minutes=51))
        assert await tick(scenario) == 0  # Slack's expiration already cleared both
        assert len(status_calls(fake_slack)) == 1 and fake_slack.calls("dnd.endSnooze") == []
    finally:
        await scenario.stop()


async def test_a_meeting_shows_in_a_meeting_and_an_early_end_clears_it(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    scenario = await started(family, fake_slack)
    try:
        meeting = a_meeting(scenario, 30)
        assert await tick(scenario) == 1
        assert status_calls(fake_slack)[-1]["profile"]["status_text"] == "In a meeting"
        assert fake_slack.calls("dnd.setSnooze") == []
        clock.advance(timedelta(minutes=10))
        scenario.app.db.execute("DELETE FROM calendar_entries WHERE id = ?", (meeting,))
        assert await tick(scenario) == 1  # it ended early: Themi takes back what it set
        assert status_calls(fake_slack)[-1]["profile"]["status_text"] == ""
    finally:
        await scenario.stop()


async def test_an_event_with_nobody_else_isnt_a_meeting(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    scenario = await started(family, fake_slack)
    try:
        a_meeting(scenario, 30, guests=0)
        assert await tick(scenario) == 0
        assert status_calls(fake_slack) == []
    finally:
        await scenario.stop()


async def test_quiet_hours_hold_notifications_and_leave_the_status(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    scenario = await started(family, fake_slack)
    try:
        scenario.app.store.update_settings(
            SYSTEM, family.erin.id, quiet_start=time(8, 30), quiet_end=time(10, 0)
        )
        assert await tick(scenario) == 1  # 09:00: quiet until 10:00
        assert [c["num_minutes"] for c in fake_slack.calls("dnd.setSnooze")] == ["60"]
        assert status_calls(fake_slack) == []
    finally:
        await scenario.stop()


async def test_a_status_michael_set_himself_is_left_alone(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    """With nothing of Themi's going on, Themi writes nothing, ever: whatever status he set
    stays. After Themi's meeting status ends on time, it doesn't clear his either."""
    scenario = await started(family, fake_slack)
    try:
        for _ in range(3):
            assert await tick(scenario) == 0
            clock.advance(timedelta(minutes=1))
        a_meeting(scenario, 5)
        assert await tick(scenario) == 1
        clock.advance(timedelta(minutes=6))
        assert await tick(scenario) == 0
        assert len(status_calls(fake_slack)) == 1
    finally:
        await scenario.stop()


async def test_it_goes_through_the_trust_tiers(family: SeededFamily, fake_slack: FakeSlack) -> None:
    scenario = await started(family, fake_slack)
    try:
        scenario.app.db.execute("UPDATE action_categories SET tier = 1 WHERE name = 'slack_status'")
        a_meeting(scenario, 30)
        await tick(scenario)
        assert status_calls(fake_slack) == []  # waiting on a yes
        pending = scenario.app.db.one(
            "SELECT summary, status FROM pending_actions WHERE category = 'slack_status'"
        )
        assert pending is not None and pending["status"] == "pending"
        assert "In a meeting" in pending["summary"]
    finally:
        await scenario.stop()


async def test_without_a_user_token_nothing_is_synced(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    scenario = await started(family, fake_slack, sync=False)
    try:
        assert scenario.app.services.maybe(SlackStatus) is None
        assert "slack_status" not in [t.name for t in scenario.app.periodic]
        assert fake_slack.calls("users.profile.set") == fake_slack.calls("dnd.setSnooze") == []
    finally:
        await scenario.stop()


async def test_the_test_button_tries_the_user_token_too(fake_slack: FakeSlack) -> None:
    from tests.fakes.slack_api import APP_TOKEN, BOT_TOKEN

    module = SlackModule(Secret(BOT_TOKEN), Secret(APP_TOKEN), user_token=Secret("xoxp-wrong"),
                         base_url=fake_slack.base_url)  # fmt: skip
    said = await module.check()
    assert said is not None and "user token" in said and "bot token" not in said
