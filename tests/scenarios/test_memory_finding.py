"""F57a: Themi finds a remembered fact when the words differ, and on a follow-up."""

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult

HOURS = "Stanford's visiting hours are 6:30-8:30 pm weekdays and 12-8:30 pm weekends."


def tool_result(scenario: Scenario) -> str:
    result = scenario.primary.last_request.messages[2].content[0]
    assert isinstance(result, ToolResult)
    return str(result.content)


async def test_the_visiting_hours_are_in_front_of_the_model_on_a_follow_up(
    scenario: Scenario,
) -> None:
    scenario.primary.queue_tool_call(
        "remember_fact",
        {
            "subject": "visiting hours",
            "fact": HOURS,
            "about": "household",
            "keywords": "Dad, hospital, visit",
        },
    )
    scenario.primary.queue_text("Got it.")
    await scenario.say(
        "Husband",
        "Remember Stanford's visiting hours are 6:30-8:30 pm weekdays and 12-8:30 pm weekends",
    )
    scenario.primary.queue_text("Sounds good.")
    await scenario.say("Husband", "Let's go see Dad at Stanford")
    scenario.primary.queue_text("Leave at 5:45.")
    await scenario.say("Husband", "what time should we leave?")
    assert f"- {HOURS}" in scenario.primary.last_request.messages[0].text


async def test_search_memory_looks_a_fact_up(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "remember_fact",
        {"subject": "visiting hours", "fact": HOURS, "about": "household", "keywords": ""},
    )
    scenario.primary.queue_text("Saved.")
    await scenario.say("Erin", "remember the visiting hours")

    scenario.primary.queue_tool_call("search_memory", {"query": "Stanford hours"})
    scenario.primary.queue_text("6:30 to 8:30 tonight.")
    assert await scenario.say("Erin", "when can I go see him?") == ["6:30 to 8:30 tonight."]
    content = tool_result(scenario)
    assert content.startswith('<data source="memory">')
    assert f"visiting hours: {HOURS}" in content


async def test_search_memory_says_when_nothing_matches(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("search_memory", {"query": "dentist"})
    scenario.primary.queue_text("I don't have that.")
    await scenario.say("Erin", "who's our dentist?")
    assert tool_result(scenario) == "Nothing remembered matches 'dentist'."

    scenario.primary.queue_tool_call("search_memory", {"query": "  "})
    scenario.primary.queue_text("Hm.")
    await scenario.say("Erin", "look it up")
    assert tool_result(scenario) == "Nothing to look for: say some words to search for."
