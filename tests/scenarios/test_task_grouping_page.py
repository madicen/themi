"""F32a (Michael's idea #170): the Tasks page grouped by due date or other ways, the choice
kept per person. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import timedelta

from tests.fixtures.web import csrf_of, sign_in, web_client
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi.standard.praise import TasksPreferences
from themi.standard.tasks import TaskBoard


def board(scenario: Scenario) -> TaskBoard:
    return scenario.app.services.get(keys.taskboard)


async def some_tasks(scenario: Scenario) -> None:
    husband, erin = scenario.member("Husband"), scenario.member("Erin")
    today = scenario.today()
    await board(scenario).create(husband, "Call the dentist", "call", 1, today, assignee=husband)
    await board(scenario).create(
        husband, "Renew the passport", "errand", 2, today + timedelta(days=20), assignee=husband
    )
    await board(scenario).create(erin, "Email the school", "text", 1, assignee=erin)


async def test_michael_groups_by_urgency_and_it_stays_that_way(scenario: Scenario) -> None:
    await some_tasks(scenario)
    async with web_client(scenario) as site:
        await sign_in(scenario, site, "Husband")
        page = (await site.get("/tasks")).text
        assert "<h2>Today (1)</h2>" in page and "<h2>Later (1)</h2>" in page
        assert 'aria-current="true">Due date</button>' in page
        refused = await site.post("/tasks/grouping", data={"csrf": "wrong", "group": "urgency"})
        assert refused.status_code == 403
        chose = await site.post("/tasks/grouping", data={"csrf": csrf_of(page), "group": "urgency"})
        assert chose.status_code == 303 and chose.headers["location"] == "/tasks"
        page = (await site.get("/tasks")).text
        assert "<h2>Urgent (1)</h2>" in page and "<h2>Neither (1)</h2>" in page
        urgent = page.split("<h2>Urgent (1)</h2>")[1].split("<h2>")[0]
        assert "Call the dentist" in urgent
        assert 'aria-current="true">Urgency</button>' in page

        shared = (await site.get("/tasks?group=kind")).text  # shown once, not saved
        assert "<h2>Calls (1)</h2>" in shared and "<h2>Errands (1)</h2>" in shared
        later = (await site.get("/tasks")).text
        assert "<h2>Urgent (1)</h2>" in later

        bad = (await site.get("/tasks?group=colour")).text
        assert "<h2>Today (1)</h2>" in bad
        await site.post("/tasks/grouping", data={"csrf": csrf_of(page), "group": "none"})
        plain = (await site.get("/tasks")).text
        assert "<h2>Today" not in plain and "Call the dentist" in plain

    husband = scenario.member("Husband")
    prefs = scenario.app.store.preferences(husband.id, TasksPreferences)
    assert prefs.task_grouping == "none"
    erin = scenario.member("Erin")
    assert scenario.app.store.preferences(erin.id, TasksPreferences).task_grouping == "due"
    async with web_client(scenario) as site:
        await sign_in(scenario, site, "Erin")
        page = (await site.get("/tasks")).text
        assert "<h2>No due date (1)</h2>" in page


async def test_saving_my_settings_keeps_the_grouping(scenario: Scenario) -> None:
    async with web_client(scenario) as site:
        await sign_in(scenario, site, "Husband")
        page = (await site.get("/tasks")).text
        await site.post("/tasks/grouping", data={"csrf": csrf_of(page), "group": "kind"})
        settings = (await site.get("/settings")).text
        assert "task_grouping" not in settings  # chosen on the page itself
        await site.post(
            "/settings", data={"csrf": csrf_of(settings), "quiet_start": "23:00",
                               "quiet_end": "07:00"}
        )  # fmt: skip
    husband = scenario.member("Husband")
    assert scenario.app.store.preferences(husband.id, TasksPreferences).task_grouping == "kind"
