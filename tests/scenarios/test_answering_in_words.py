"""Answering a waiting card in a sentence ("Yes, let's give that one a try. How often...?").

Erin said yes to the water check-in in words, but it stayed waiting: only a tap or a bare
"yes" could answer a card. The model can now answer one, but only when the person's own
message says so; it can't say yes for them."""

from tests.scenarios.harness import Scenario
from themi.core.habits import CATEGORY, EXECUTOR, HabitReserve


async def water_offer(scenario: Scenario) -> int:
    erin = scenario.member("Erin")
    HabitReserve(scenario.app.services).seed(erin)
    habit = scenario.app.db.one(
        "SELECT id FROM habits WHERE member_id = ? AND idea LIKE '%water%'", (erin.id,)
    )
    assert habit is not None
    await scenario.app.services.autonomy.stage(
        CATEGORY,
        erin,
        "Something you could try for yourself: a glass of water mid-morning",
        {"habit": habit["id"]},
        EXECUTOR,
    )
    scenario.app.db.execute("UPDATE habits SET status = 'offered' WHERE id = ?", (habit["id"],))
    return habit["id"]


def habit_status(scenario: Scenario, habit_id: int) -> str:
    return scenario.app.db.scalar("SELECT status FROM habits WHERE id = ?", (habit_id,))


def answer(decision: str) -> dict:
    return {"item": "a glass of water mid-morning", "decision": decision}


async def test_a_yes_in_a_sentence_answers_the_card(scenario: Scenario) -> None:
    habit = await water_offer(scenario)
    scenario.primary.queue_tool_call("answer_waiting_item", answer("yes"))
    scenario.primary.queue_text("Trying it. Offers like that come up every couple of weeks.")
    await scenario.say("Erin", "Yes let's give that one a try. How often do you suggest these?")
    assert habit_status(scenario, habit) == "active"
    assert scenario.app.services.awaiting(scenario.member("Erin")) == []


async def test_the_model_cant_say_yes_for_them(scenario: Scenario) -> None:
    habit = await water_offer(scenario)
    scenario.primary.queue_tool_call("answer_waiting_item", answer("yes"))
    scenario.primary.queue_text("It was just an idea to try.")
    await scenario.say("Erin", "What prompted you to send me the water check in?")
    assert habit_status(scenario, habit) == "offered"
    result = scenario.primary.last_request.messages[-1].content[0]
    assert "they haven't said" in str(result)


async def test_a_no_in_words_sets_it_aside(scenario: Scenario) -> None:
    habit = await water_offer(scenario)
    scenario.primary.queue_tool_call("answer_waiting_item", answer("no"))
    scenario.primary.queue_text("Dropped it.")
    await scenario.say("Erin", "Nah, drop the water one please")
    assert habit_status(scenario, habit) != "active"
    assert scenario.app.services.awaiting(scenario.member("Erin")) == []
