"""CR8a: the system prompt, composed from the template's persona and each part's rules."""

from __future__ import annotations

import pytest

from tests.fakes.modules import module_context
from tests.fakes.prompt import FAMILY_SYSTEM
from tests.fixtures.family import SeededFamily
from themi.config import load_template
from themi.core import (
    appliances,
    connector_modules,
    follow_ups,
    google_modules,
    home_modules,
    liaison,
    lists,
    memory,
    spending,
    tasks,
)
from themi.core.prompts import CORE_RULES
from themi.modules.prompt import PromptFragment, compose_system

EVERY_MODULE_RULES = (
    *tasks.PROMPT_RULES,
    *appliances.PROMPT_RULES,
    *memory.PROMPT_RULES,
    *home_modules.CHORE_PROMPT_RULES,
    *google_modules.CALENDAR_PROMPT_RULES,
    *connector_modules.TRAVEL_PROMPT_RULES,
    *liaison.PROMPT_RULES,
    *spending.PROMPT_RULES,
    *lists.PROMPT_RULES,
    *follow_ups.PROMPT_RULES,
)


def test_the_family_prompt_is_its_parts() -> None:
    persona = load_template("family").persona
    assert compose_system(persona, [*CORE_RULES, *EVERY_MODULE_RULES]) == FAMILY_SYSTEM
    assert compose_system(persona, [*EVERY_MODULE_RULES, *CORE_RULES]) == FAMILY_SYSTEM


def test_a_module_left_out_takes_its_rules_with_it() -> None:
    persona = load_template("family").persona
    without = [f for f in EVERY_MODULE_RULES if f not in liaison.PROMPT_RULES]
    system = compose_system(persona, [*CORE_RULES, *without])
    assert "relay_to_partner" not in system and "who calls whom" not in system
    assert "Never tell anyone to take a dose" in system  # the tasks module's stays
    assert system.endswith("not a note.\n")


def test_a_template_rewords_or_removes_a_rule_by_its_key() -> None:
    rule = PromptFragment("x.one", "act", 10, "- One.")
    other = PromptFragment("x.two", "act", 20, "- Two.")
    assert compose_system("Hi.", [rule, other]) == "Hi.\n\nHow you act:\n- One.\n- Two.\n"
    reworded = compose_system("Hi.", [rule, other], {"x.one": "- Uno."})
    assert reworded == "Hi.\n\nHow you act:\n- Uno.\n- Two.\n"
    assert compose_system("Hi.", [rule, other], {"x.one": ""}).count("- ") == 1
    assert compose_system("Hi.", []) == "Hi.\n"  # a section with no rules isn't shown


def test_two_fragments_with_one_key_are_refused() -> None:
    rule = PromptFragment("x.one", "act", 10, "- One.")
    with pytest.raises(ValueError, match=r"two prompt fragments with the key x\.one"):
        compose_system("Hi.", [rule, rule])


def test_every_key_is_unique_and_names_its_owner() -> None:
    keys = [f.key for f in (*CORE_RULES, *EVERY_MODULE_RULES)]
    assert len(keys) == len(set(keys))
    assert all(f.key.startswith("core.") for f in CORE_RULES)


def test_a_module_adds_its_rules_when_it_installs(family: SeededFamily) -> None:
    ctx = module_context(family.store)
    ctx.load(lists.ListsModule())
    assert ctx.services.prompt_fragments == list(lists.PROMPT_RULES)
