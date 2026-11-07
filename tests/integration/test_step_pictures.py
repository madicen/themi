"""BD4b: a picture for each guided step: the order they're made in, reuse for a task's
saved steps, the cap and failures, and who may see them. The clock starts Wednesday 21
October 2026, 9 am."""

from __future__ import annotations

import httpx

from tests.fakes.scripted_provider import TINY_PNG
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.ai.errors import PermanentError
from themi.core.body_double import GUIDED, BodyDouble
from themi.core.step_images import CAPPED_TEXT, StepPictures
from themi.core.tasks import Task

STEPS = ["Clear the counter", "Load the dishwasher", "Wipe the stovetop", "Sweep"]


def bd(scenario: Scenario) -> BodyDouble:
    assert scenario.app.services.body_double is not None
    return scenario.app.services.body_double


def pictures(scenario: Scenario) -> StepPictures:
    found = bd(scenario).pictures
    assert isinstance(found, StepPictures)
    return found


async def kitchen(scenario: Scenario, owner: str = "Erin") -> Task:
    board = scenario.app.services.taskboard
    assert board is not None
    member = scenario.member(owner)
    task = await board.create(member, "Clean the kitchen", "physical", 3)
    await board.update(task.id, member, steps=STEPS)
    return task


def image_prompts(scenario: Scenario) -> list[str]:
    return [r.prompt for r in scenario.primary.requests if r.op == "image"]


async def test_the_current_step_first_then_the_rest_in_order(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    task = await kitchen(scenario)
    session, _, _ = await bd(scenario).start(erin, mode=GUIDED, task=task)
    scenario.app.db.execute("UPDATE body_double_sessions SET step = 2 WHERE id = ?",
                            (session.id,))  # fmt: skip
    await scenario.run_jobs()
    made = [p.split("chore (")[1].split(")")[0] for p in image_prompts(scenario)]
    assert made == ["wipe the stovetop", "sweep", "clear the counter", "load the dishwasher"]
    row = pictures(scenario).row(session.id, 0)
    assert row is not None and row["status"] == "ready"
    path = pictures(scenario).path(row)
    assert path is not None and path.read_bytes() == TINY_PNG


async def test_a_tasks_saved_steps_reuse_their_pictures(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    task = await kitchen(scenario)
    await bd(scenario).start(erin, mode=GUIDED, task=task)
    await scenario.run_jobs()
    asked = len(image_prompts(scenario))
    second, _, _ = await bd(scenario).start(erin, mode=GUIDED, task=task)
    await scenario.run_jobs()
    assert len(image_prompts(scenario)) == asked  # none made again
    row = pictures(scenario).row(second.id, 3)
    assert row is not None and row["status"] == "ready"


async def test_past_the_cap_the_steps_are_text(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    scenario.app.db.execute("UPDATE members SET image_daily_cap = 2 WHERE id = ?", (erin.id,))
    task = await kitchen(scenario)
    session, _, _ = await bd(scenario).start(erin, mode=GUIDED, task=task)
    await scenario.run_jobs()
    assert len(image_prompts(scenario)) == 2
    statuses = [pictures(scenario).row(session.id, i)["status"] for i in range(4)]  # type: ignore[index]
    assert statuses == ["ready", "ready", "capped", "capped"]
    fresh = bd(scenario).get(session.id)
    assert fresh is not None
    state = pictures(scenario).page_state(fresh)
    assert state["note"] == CAPPED_TEXT and state["picture"]["status"] == "ready"


async def test_a_picture_that_fails_leaves_the_text(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    task = await kitchen(scenario)
    scenario.primary.queue_error(PermanentError("no"), "image")
    scenario.fallback.queue_error(PermanentError("no"), "image")
    session, _, _ = await bd(scenario).start(erin, mode=GUIDED, task=task)
    await scenario.run_jobs()
    row = pictures(scenario).row(session.id, 0)
    assert row is not None and row["status"] == "failed"
    fresh = bd(scenario).get(session.id)
    assert fresh is not None
    assert pictures(scenario).page_state(fresh) == {"picture": {"status": "none"}}
    assert pictures(scenario).row(session.id, 1)["status"] == "ready"  # type: ignore[index]


async def test_only_the_owner_sees_the_pictures(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    task = await kitchen(scenario, "Husband")
    session, _, _ = await bd(scenario).start(scenario.member("Husband"), mode=GUIDED, task=task)
    await scenario.run_jobs()
    await sign_in(scenario, site, "Erin")
    assert (await site.get(f"/session/pictures/{session.id}/0")).status_code == 404
    async with httpx.AsyncClient(transport=site._transport, base_url="http://themi.test") as his:
        await sign_in(scenario, his, "Husband")
        got = await his.get(f"/session/pictures/{session.id}/0")
        assert got.status_code == 200 and got.content == TINY_PNG
