"""BD1a: body double sessions against the app: block timers on a frozen clock, the pause,
outcomes and switching. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import timedelta

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core.body_double import JOB, SILENT, SPRINT, BodyDouble


def bd(scenario: Scenario) -> BodyDouble:
    assert scenario.app.services.body_double is not None
    return scenario.app.services.body_double


def held(scenario: Scenario) -> list[str]:
    return [p.topic for p in scenario.app.services.outbox.pauses.active(scenario.member("Erin"))]


async def test_a_session_holds_nudges_with_its_own_topic(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    session, _, _ = await bd(scenario).start(erin, mode=SILENT, minutes=30)
    assert held(scenario) == ["body_double"]
    pause = scenario.app.db.one("SELECT until FROM pauses WHERE id = ?", (session.pause_id,))
    assert pause is not None
    assert pause["until"] == "2026-10-21T17:30:00+00:00"  # 9:30 local, and an hour to answer
    await bd(scenario).end(erin, finished=False)
    assert held(scenario) == []


async def test_an_open_session_asks_after_four_hours(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    await bd(scenario).start(erin, mode=SILENT)
    clock.advance(timedelta(hours=3, minutes=59))
    await scenario.run_jobs()
    assert "That's four hours. How did it go?" not in scenario.inbox("Erin")
    clock.advance(timedelta(minutes=1))
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "That's four hours. How did it go?"


async def test_a_bit_longer_moves_the_end(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    await bd(scenario).start(erin, mode=SILENT, minutes=60)
    clock.advance(timedelta(hours=1))
    await scenario.run_jobs()
    await scenario.tap("Erin", "A bit longer")
    assert scenario.edits("Erin")[-1]["text"] == "A bit longer, then: quiet until 10:15 am."
    clock.advance(timedelta(minutes=15))
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "That's 75 minutes. How did it go?"


async def test_an_old_job_is_stale_after_a_change(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    session, _, _ = await bd(scenario).start(erin, mode=SPRINT)
    jobs = scenario.app.db.query("SELECT payload FROM job_queue WHERE kind = ?", (JOB,))
    assert len(jobs) == 1
    await bd(scenario).switch(erin, SILENT)  # the sprint's job no longer counts
    clock.advance(timedelta(minutes=25))
    await scenario.run_jobs()
    assert "That's 25 minutes. Break for 5?" not in scenario.inbox("Erin")
    old = bd(scenario).get(session.id)
    assert old is not None and old.outcome == "switched"


async def test_a_switch_keeps_the_start_and_the_task(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    board = scenario.app.services.taskboard
    assert board is not None
    task = await board.create(erin, "Write the essay", "text", 4)
    first, _, _ = await bd(scenario).start(erin, mode=SILENT, task=task)
    clock.advance(timedelta(minutes=10))
    second, text, _ = await bd(scenario).switch(erin, SPRINT)
    assert text == "Sprints instead: 25 minutes on, then a 5-minute break."
    assert second.started_at == first.started_at
    assert second.task_id == task.id
    assert second.row["switched_from"] == first.id


async def test_a_new_session_ends_the_old(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    first, _, _ = await bd(scenario).start(erin, mode=SILENT)
    await bd(scenario).start(erin, mode=SPRINT)
    old = bd(scenario).get(first.id)
    assert old is not None and old.outcome == "stopped"
    assert held(scenario) == ["body_double"]  # the new one's pause


async def test_burnout_mode_ends_a_session(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    first, _, _ = await bd(scenario).start(erin, mode=SILENT)
    assert scenario.app.services.burnout is not None
    await scenario.app.services.burnout.start(erin)
    old = bd(scenario).get(first.id)
    assert old is not None and old.outcome == "stopped"
    assert "body_double" not in held(scenario)


async def test_the_hour_of_the_week_is_kept(scenario: Scenario) -> None:
    session, _, _ = await bd(scenario).start(scenario.member("Erin"), mode=SILENT)
    assert session.row["hour_of_week"] == 2 * 24 + 9  # Wednesday, 9 am local


# ----- BD2 ----------------------------------------------------------------------------------


async def test_their_own_default_always_wins(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    modes = bd(scenario).modes
    assert modes is not None
    modes.set_default(erin, "tidy", "guided")
    scenario.primary.queue_structured({"steps": [{"text": "Pick up toys", "optional": False}]})
    session, text, buttons = await bd(scenario).start(erin, label="declutter the playroom")
    assert (session.mode, session.category) == ("guided", "tidy")
    assert not text.startswith("Taking this one")  # their choice: no offer
    assert "Sprints instead" not in [b.label for b in buttons]


async def test_a_tasks_category_is_kept_and_can_be_corrected(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    board = scenario.app.services.taskboard
    assert board is not None
    task = await board.create(erin, "Walk the dog", "physical", 3)
    scenario.primary.queue_structured({"category": "chores"})
    await bd(scenario).start(erin, task=task, mode=SILENT)
    assert scenario.app.db.scalar("SELECT category FROM tasks WHERE id = ?", (task.id,)) == (
        "chores"
    )
    assert '<data source="the job">\nWalk the dog\n</data>' in scenario.primary.requests[-1].prompt
    scenario.primary.queue_tool_call("set_job_category", {"task_id": 0, "category": "other"})
    scenario.primary.queue_text("Noted.")
    await scenario.say("Erin", "that's not a chore, it's just a walk")
    assert scenario.app.db.scalar("SELECT category FROM tasks WHERE id = ?", (task.id,)) == (
        "other"
    )
    await bd(scenario).start(erin, task=task, mode=SILENT)  # kept: no call this time
    row = scenario.app.db.one("SELECT category FROM body_double_sessions ORDER BY id DESC")
    assert row is not None and row["category"] == "other"


async def test_the_settings_page_has_a_row_per_kind_of_job(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    page = await site.get("/settings")
    for category in ("deep_work", "admin", "chores", "tidy", "other"):
        assert f'name="job_mode_{category}"' in page.text
    form = {
        "csrf": csrf, "quiet_start": "22:00", "quiet_end": "07:00", "daily_limit": "8",
        "sprint_work_minutes": "25", "sprint_break_minutes": "5", "break_extend_minutes": "15",
        "job_mode_tidy": "sprint", "job_mode_admin": "",
    }  # fmt: skip
    await site.post("/settings", data=form)
    modes = bd(scenario).modes
    assert modes is not None
    assert modes.defaults(scenario.member("Erin")) == {"tidy": "sprint"}
