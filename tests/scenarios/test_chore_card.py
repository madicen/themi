"""DC9: "show the chore chart" sends a picture of what's up for each person: never what
waits off the chart."""

from __future__ import annotations

from datetime import timedelta

from tests.scenarios.harness import Scenario
from themi.core import keys
from themi.standard.tasks import TaskBoard
from themi_home.chore_card import CAPTION, chart_data
from themi_home.chore_chart import ChartPreferences


async def chores(scenario: Scenario) -> None:
    board = scenario.app.services.get(keys.taskboard)
    assert isinstance(board, TaskBoard)
    queue = scenario.app.services.get(keys.chart_queue)
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    today = scenario.today()
    scenario.app.store.save_preferences(erin, erin.id, ChartPreferences, chart_limit=1)
    for who, title, due in (
        (erin, "Dishes", today - timedelta(days=1)),
        (erin, "Fold the towels", today),
        (husband, "Take out the trash", today),
    ):
        task = await board.create(who, title, "physical", 1, due, assignee=who, nudge=False)
        await queue.put_on(task.id, who)
    await board.create(erin, "Call the bank", "call", 1, today, assignee=erin, nudge=False)


async def test_the_chart_shows_whats_up_and_nothing_waiting(scenario: Scenario) -> None:
    await chores(scenario)
    queue = scenario.app.services.get(keys.chart_queue)
    data = chart_data(queue, scenario.app.store.list_members(), scenario.today())
    shown = {c.name: [chore.title for chore in c.chores] for c in data.columns}
    assert shown["Erin"] == ["Dishes"]  # her limit is one: the towels wait off the chart
    assert shown["Husband"] == ["Take out the trash"]
    assert "Call the bank" not in str(shown)  # a to-do, not a chore


async def test_asking_sends_the_picture(scenario: Scenario) -> None:
    await chores(scenario)
    scenario.primary.queue_tool_call("show_chore_chart", {})
    scenario.primary.queue_text("There it is.")
    replies = await scenario.say("Erin", "Show me the chore chart")
    assert CAPTION in replies
    assert len(scenario.pictures("Erin")) == 1
