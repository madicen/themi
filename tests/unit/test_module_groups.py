"""MP1: the groups the Modules page lists modules in."""

from __future__ import annotations

import pytest

from themi.config import available_modules
from themi.modules import Module, ModuleError
from themi.modules.groups import (
    OTHER,
    ModuleGroup,
    group_of,
    guests,
    known_groups,
    members,
    starter,
    tree,
)
from themi_home.groups import COOKING


def test_every_shipped_module_names_a_group() -> None:
    known = available_modules()
    assert [n for n, c in known.items() if group_of(c) is OTHER] == []


def test_groups_come_in_page_order_and_core_names_no_packs_group() -> None:
    ids = [g.id for g in known_groups(available_modules().values())]
    assert ids[:5] == ["talking", "ai", "voice_and_pictures", "tasks", "your_day"]
    assert ids[-2:] == ["services", "behind_the_scenes"]
    assert ids.index("body_doubling") < ids.index("cooking") < ids.index("email")
    import themi.modules.groups as core

    assert not any(isinstance(v, ModuleGroup) and v.id == "cooking" for v in vars(core).values())


def test_a_module_without_a_group_is_under_other() -> None:
    class Loose(Module):
        name = "loose"

    assert group_of(Loose) is OTHER
    assert [g.id for g in known_groups([Loose])] == ["other"]


def test_two_groups_with_one_id_are_refused() -> None:
    class A(Module):
        name = "a"
        group = ModuleGroup("x", "X", "", 1)

    class B(Module):
        name = "b"
        group = ModuleGroup("x", "Not X", "", 1)

    with pytest.raises(ModuleError, match="called x"):
        known_groups([A, B])


def test_add_ons_sit_under_what_they_build_on() -> None:
    known = available_modules()
    titles = {n: c.title for n, c in known.items()}
    rows = tree(members(COOKING, known), known, titles)
    depth = dict(rows)
    assert rows[0] == ("recipes", 0)
    assert depth["recipe_groceries"] == 1 and depth["cooking"] == 2
    assert depth["cooking_timers"] == 3 and depth["recipe_ideas"] == 2
    assert depth["gram_weights"] == 1  # it needs Guides too, but that's another group
    order = [n for n, _ in rows]
    assert order.index("cooking") < order.index("cooking_timers") < order.index("recipe_ideas")


def test_guests_and_starter_sets() -> None:
    known = available_modules()
    assert guests(COOKING, known) == ["meals", "smarthq"]
    assert "smarthq" not in members(COOKING, known)
    by_id = {g.id: g for g in known_groups(known.values())}
    assert starter(by_id["ai"], known) == ["gemini"]
    assert "step_pictures" not in starter(by_id["body_doubling"], known)
    assert "roborock" not in starter(by_id["home"], known)
    # no starter named: everything that needs no account
    email = starter(by_id["email"], known)
    assert "gmail" in email and "email_triage" in email
