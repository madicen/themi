"""Idea #25: wall items Themi makes get an emoji that fits, in the wall's own format."""

import pytest

from themi.connectors.cozyla.emoji import better_icon, chore_icon, needs_icon, routine_icon


@pytest.mark.parametrize(
    ("title", "icon"),
    [
        ("Clean the bird cage", "czl_chores_emoji#_#parrot#_#🦜"),
        ("Refill auto feeders", "czl_chores_emoji#_#bowl_with_spoon#_#🥣"),
        ("Bring bins in", "czl_chores_emoji#_#wastebasket#_#🗑️"),
        ("Mimi pill - 1 tab", "czl_chores_emoji#_#pill#_#💊"),
        ("Fix upstairs litter box", "czl_chores_emoji#_#cat#_#🐈"),
        ("Change sheets (upstairs bed and couch)", "czl_chores_emoji#_#bed#_#🛏️"),
        ("Vacuum upstairs bedroom", "czl_chores_emoji#_#broom#_#🧹"),  # nothing closer
    ],
)
def test_chores_get_a_fitting_emoji(title: str, icon: str) -> None:
    assert chore_icon(title) == icon


def test_routines_use_the_routine_format() -> None:
    assert routine_icon("Go for a run") == "czl_routine_emoji#_#person_running#_#🏃"
    assert routine_icon("Replace vacuum water") == "czl_routine_emoji#_#droplet#_#💧"
    assert routine_icon("Something else entirely") == "routine_property_bed"  # the default


def test_only_themis_own_defaults_are_replaced() -> None:
    """Icons the family chose stay."""
    assert needs_icon("") and needs_icon("czl_chores_emoji#_#broom#_#🧹")
    assert needs_icon("routine_property_bed")
    assert not needs_icon("czl_chores_emoji#_#paw_prints#_#🐾")
    assert not needs_icon("walk_dog")


def test_no_icon_isnt_swapped_for_a_plain_default() -> None:
    """A wall item with no icon and nothing that fits (Mimi's chin cream) is left alone."""
    assert not better_icon("", chore_icon("Mimi chin cream - evening"))
    assert better_icon("", chore_icon("Mimi pill - 1 tab"))
