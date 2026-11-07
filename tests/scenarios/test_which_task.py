"""P8b: which open task a message names is decided by meaning (embeddings), with the word
check as the fallback. The fake model has one axis per topic, so a paraphrase lands on its
task's topic and a shared word ("ran", "clean") doesn't."""

from __future__ import annotations

import pytest

from tests.fakes.embedder import TopicEmbedder
from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.tasks import Task, TaskBoard

TOPICS = TopicEmbedder(
    {
        "run": ("run", "jog", "5k", "miles"),
        "dishes": ("dishwasher",),
        "bins": ("bins", "garbage cans"),
        "babysitting": ("parents", "sitter", "babysit"),
        "cage": ("cage", "birds"),
        "car": ("car",),
        "clean": ("clean", "wipe"),
        "kitchen": ("kitchen",),
        "declutter": ("declutter", "counters"),
        "bathroom": ("bathroom",),
        "cardboard": ("cardboard", "boxes"),
        "tea": ("tea",),
        "feeders": ("feeders", "pets"),
    }
)


@pytest.fixture
def meaning(scenario: Scenario) -> Scenario:
    scenario.primary.embed_with = TOPICS
    return scenario


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.maybe(keys.taskboard) is not None
    return scenario.app.services.get(keys.taskboard)


async def tasks(scenario: Scenario, *titles: str) -> list[Task]:
    erin = scenario.member("Erin")
    return [await board(scenario).create(erin, t, "physical", 1, assignee=erin) for t in titles]


async def themi_said(scenario: Scenario, text: str) -> None:
    await scenario.app.services.outbox.send(scenario.member("Erin"), text, priority=Priority.REPLY)


async def done(scenario: Scenario, said: str, *done_tasks: Task) -> list[ToolResult]:
    """The model marks these done for what Erin said; the tool results, in order."""
    for task in done_tasks:
        scenario.primary.queue_tool_call("complete_task", {"task_id": task.id})
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", said)
    return [
        block
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-len(done_tasks) :]


def status(scenario: Scenario, task: Task) -> str:
    return board(scenario).get(task.id).status


async def test_a_paraphrase_the_words_miss_is_accepted(meaning: Scenario) -> None:
    run, _ = await tasks(meaning, "Go for a run", "Bring bins in")
    await themi_said(meaning, "Reminder set for tomorrow at 9 am.")
    await done(meaning, "jogged this morning", run)
    assert status(meaning, run) == "done"


async def test_one_shared_word_no_longer_names_a_task(meaning: Scenario) -> None:
    run, kitchen, _, _ = await tasks(
        meaning, "Go for a run", "Clean the kitchen", "Clean left bathroom", "Clean right bathroom"
    )
    [result] = await done(meaning, "I ran the dishwasher after dinner", run)
    assert result.is_error and "nothing they said names Go for a run" in result.content
    [result] = await done(meaning, "I cleaned the car this morning", kitchen)
    assert result.is_error and status(meaning, kitchen) == "open"


async def test_the_bins_stay_refused_for_the_parents(meaning: Scenario) -> None:
    bins, parents = await tasks(meaning, "Bring bins in", "Contact Sam's parents about babysitting")
    [result] = await done(meaning, "We contacted Sam's parents", bins)
    assert result.is_error and f"names task {parents.id}" in result.content
    assert status(meaning, bins) == "open"


async def test_yes_please_is_read_with_the_question_it_answers(meaning: Scenario) -> None:
    """#92: "Yes please" to moving the parents' task moved the bird cage."""
    cage, parents = await tasks(
        meaning, "Clean the bird cage", "Contact Sam's parents about babysitting"
    )
    await themi_said(
        meaning, 'Should I move "Contact Sam\'s parents about babysitting" to today at 6 pm?'
    )
    [result] = await done(meaning, "Yes please", cage)
    assert result.is_error and f"names task {parents.id}" in result.content


async def test_near_twins_pick_the_one_meant(meaning: Scenario) -> None:
    clean, declutter = await tasks(meaning, "Clean the kitchen", "Declutter the kitchen")
    [result] = await done(meaning, "Kitchen's decluttered", clean)
    assert result.is_error and f"names task {declutter.id}" in result.content
    await done(meaning, "Kitchen's decluttered", declutter)
    assert status(meaning, declutter) == "done"


async def test_all_done_after_a_list_marks_each_on_it(meaning: Scenario) -> None:
    tea, feeders, run = await tasks(
        meaning, "Drink green tea", "Refill pet feeders", "Go for a run"
    )
    await themi_said(meaning, "Still on for tonight: Drink green tea, Refill pet feeders.")
    *_, refused = await done(meaning, "All done!", tea, feeders, run)
    assert (status(meaning, tea), status(meaning, feeders)) == ("done", "done")
    assert refused.is_error and status(meaning, run) == "open"


async def test_both_bathrooms_marks_both_and_nothing_else(meaning: Scenario) -> None:
    left, right, kitchen = await tasks(
        meaning, "Clean left bathroom", "Clean right bathroom", "Clean the kitchen"
    )
    *_, refused = await done(meaning, "Both bathrooms are clean", left, right, kitchen)
    assert (status(meaning, left), status(meaning, right)) == ("done", "done")
    assert refused.is_error and status(meaning, kitchen) == "open"


async def test_all_in_a_sentence_doesnt_name_every_task(meaning: Scenario) -> None:
    cardboard, run = await tasks(meaning, "Process the cardboard outside", "Go for a run")
    [_, refused] = await done(meaning, "Broke down all the boxes in the yard", cardboard, run)
    assert status(meaning, cardboard) == "done"
    assert refused.is_error and status(meaning, run) == "open"


async def test_a_message_equally_close_to_two_tasks_is_refused(meaning: Scenario) -> None:
    left, _ = await tasks(meaning, "Clean left bathroom", "Clean right bathroom")
    [result] = await done(meaning, "The bathroom is done", left)
    assert result.is_error and status(meaning, left) == "open"


async def test_without_embeddings_the_word_check_decides(scenario: Scenario) -> None:
    """Neither fake model can embed: the words decide, "ran" naming the run as before."""
    [run] = await tasks(scenario, "Go for a run")
    await done(scenario, "Ran the dishwasher", run)
    assert status(scenario, run) == "done"


async def test_a_slow_embedder_leaves_the_word_check_to_decide(meaning: Scenario) -> None:
    [run] = await tasks(meaning, "Go for a run")
    meaning.primary.take(0)  # the model's call
    meaning.primary.take(3)  # the embedding: over the second it's allowed
    await done(meaning, "Ran the dishwasher", run)
    assert status(meaning, run) == "done"  # the words' answer, not the embeddings'


async def test_did_my_5k_says_its_done(scenario: Scenario) -> None:
    """P8a's Notes: a leading "did" read "did my 5k" as a question."""
    run, cage = await tasks(scenario, "Go for a run", "Clean the bird cage")
    await themi_said(scenario, "Go for a run: done already, or later?")
    await done(scenario, "did my 5k", run)
    assert status(scenario, run) == "done"
    [result] = await done(scenario, "Did I clean the bird cage", cage)
    assert result.is_error and "question" in result.content


async def test_titles_are_embedded_once(meaning: Scenario) -> None:
    run, bins = await tasks(meaning, "Go for a run", "Bring bins in")
    await done(meaning, "jogged this morning", run)
    await done(meaning, "the garbage cans are back in", bins)
    embedded = [r.texts for r in meaning.primary.requests if r.op == "embed"]
    assert embedded[-1] == ("the garbage cans are back in",)
