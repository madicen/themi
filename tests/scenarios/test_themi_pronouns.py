"""F35a (Erin's idea #176): Themi's pronouns, one choice for the family. The list is the
prompt's stand-in until Erin gives hers: it/its, she/her, he/him, they/them, just the name."""

from __future__ import annotations

import re

import httpx
import pytest

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_conversation_mode import chat_on, queue_nothing_picked_out
from themi.core.pronouns import CHOICES, PronounSettings, pronouns, system_line

THIRD_PERSON = re.compile(r"\b(?:it|its|itself|she|her|herself|he|him|his|himself|they|them|"
                          r"their|themself)\b", re.IGNORECASE)  # fmt: skip


def choose(scenario: Scenario, choice: str) -> None:
    scenario.app.store.set_household_value(PronounSettings.module, "themi_pronouns", choice)


@pytest.mark.parametrize("choice", ["she", "he", "they", "name"])
async def test_each_choice_reaches_both_system_prompts(scenario: Scenario, choice: str) -> None:
    choose(scenario, choice)
    line = system_line(choice)
    scenario.primary.queue_text("Morning!")
    await scenario.say("Husband", "hi")
    assert line in scenario.primary.requests[-1].system
    await chat_on(scenario, "Erin")
    scenario.primary.queue_text("That sounds like a lot.")
    queue_nothing_picked_out(scenario)
    await scenario.say("Erin", "long day, the kids were a lot")
    chats = [r for r in scenario.primary.requests if not r.tools]
    assert line in chats[0].system


async def test_the_default_stays_it_and_adds_nothing(scenario: Scenario) -> None:
    assert scenario.app.store.household(PronounSettings).themi_pronouns == "it"
    assert system_line("it") == ""
    scenario.primary.queue_text("Morning!")
    await scenario.say("Erin", "hi")
    assert "Themi uses" not in scenario.primary.requests[-1].system


def test_just_the_name_leaves_no_pronoun_in_the_templates() -> None:
    words = pronouns("name")
    for text in (words.on_own, words.back, words.will):
        assert not THIRD_PERSON.search(text.replace("Themi", "")), text
    assert pronouns("they").on_own == "on their own" and pronouns("she").back == "she's back"
    assert set(CHOICES) == {"it", "she", "he", "they", "name"}


async def test_the_pages_say_it_with_the_chosen_pronoun(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    assert "What Themi does on its own" in (await site.get("/tiers")).text
    choose(scenario, "she")
    assert "What Themi does on her own" in (await site.get("/tiers")).text
    choose(scenario, "name")
    assert "What Themi does on Themi&#39;s own" in (await site.get("/tiers")).text


async def test_erin_sets_they_on_the_website_and_michaels_next_turn_uses_it(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    assert 'name="themi_pronouns"' in page
    await site.post("/settings", data={"csrf": csrf, "themi_pronouns": "they", "phrasing": "plain"})
    assert scenario.app.store.household(PronounSettings).themi_pronouns == "they"
    scenario.primary.queue_text("Passed on.")
    await scenario.say("Husband", "tell Erin I'm running late")
    assert system_line("they") in scenario.primary.requests[-1].system


async def test_changing_it_in_chat_says_so_in_a_line(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("set_themi_pronouns", {"pronouns": "she"})
    await scenario.say("Erin", "Themi, can you use she/her for yourself?")
    assert scenario.app.store.household(PronounSettings).themi_pronouns == "she"
    assert scenario.inbox("Erin")[-1] == "Done. I'll go by she/her."
