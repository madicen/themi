"""CR7a: a member's preferences for one module, kept in member_preferences."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.family import SeededFamily, seed_family
from themi.accounts import AccountStore, InvalidValue
from themi.accounts.store import PermissionDenied
from themi.core.body_double import BodyDoublePreferences
from themi.core.breaks import BreaksPreferences
from themi.core.chore_chart import ChartPreferences
from themi.storage import migrations
from themi.storage.db import Database
from themi.storage.secrets import Cipher, generate_key


def test_a_member_who_never_set_them_gets_the_defaults(family: SeededFamily) -> None:
    family.db.execute("DELETE FROM member_preferences")
    prefs = family.store.preferences(family.erin.id, BodyDoublePreferences)
    assert (prefs.sprint_work_minutes, prefs.sprint_break_minutes) == (25, 5)
    assert (prefs.body_double_sound, prefs.body_double_volume) == ("lofi", 50)
    assert family.store.preferences(family.erin.id, BreaksPreferences).break_extend_minutes == 15
    chart = family.store.preferences(family.erin.id, ChartPreferences)
    assert (chart.chart_limit, chart.chart_counts_shared) == (0, True)


def test_saved_values_are_theirs_and_only_the_changed_ones_are_written(
    family: SeededFamily,
) -> None:
    family.db.execute("DELETE FROM member_preferences")
    store, erin = family.store, family.erin
    saved = store.save_preferences(erin, erin.id, ChartPreferences, chart_limit=2)
    assert (saved.chart_limit, saved.chart_counts_shared) == (2, True)
    rows = family.db.query("SELECT module, key, value FROM member_preferences")
    assert [(r["module"], r["key"], json.loads(r["value"])) for r in rows] == [
        ("cozyla_chores", "chart_limit", 2)
    ]
    assert store.preferences(family.husband.id, ChartPreferences).chart_limit == 0
    store.save_preferences(erin, erin.id, ChartPreferences, chart_counts_shared=False)
    chart = store.preferences(erin.id, ChartPreferences)
    assert (chart.chart_limit, chart.chart_counts_shared) == (2, False)


def test_only_the_member_themselves_changes_them(family: SeededFamily) -> None:
    with pytest.raises(PermissionDenied):
        family.store.save_preferences(
            family.husband, family.erin.id, BreaksPreferences, break_extend_minutes=30
        )


@pytest.mark.parametrize(
    ("model", "change", "words"),
    [
        (BodyDoublePreferences, {"sprint_work_minutes": 4}, "a sprint's work block is between"),
        (BodyDoublePreferences, {"sprint_break_minutes": 31}, "a sprint's break is between"),
        (BodyDoublePreferences, {"body_double_sound": "loud"}, "the sounds are lofi"),
        (BodyDoublePreferences, {"body_double_volume": 101}, "the volume is between 0 and 100"),
        (BreaksPreferences, {"break_extend_minutes": 121}, "a break's extension is between"),
        (ChartPreferences, {"chart_limit": 11}, "chores at a time is between 0 and 10"),
    ],
)
def test_a_value_out_of_range_says_so_in_the_old_words(
    family: SeededFamily, model: type, change: dict[str, object], words: str
) -> None:
    with pytest.raises(InvalidValue, match=words):
        family.store.save_preferences(family.erin, family.erin.id, model, **change)


def test_the_migration_copies_each_members_values(tmp_path: Path) -> None:
    db = Database(tmp_path / "old.db")
    before = [m for m in migrations.discover() if m.version < 145]
    migrations.apply(db, before)
    family = seed_family(AccountStore(db, Cipher(generate_key())))
    db.execute(
        "UPDATE members SET sprint_work_minutes = 40, sprint_break_minutes = 8, "
        "body_double_sound = 'rain', body_double_volume = 20, break_extend_minutes = 30, "
        "chart_limit = 1, chart_counts_shared = 0 WHERE id = ?",
        (family.erin.id,),
    )
    migrations.apply(db)
    store = family.store
    bd = store.preferences(family.erin.id, BodyDoublePreferences)
    assert (bd.sprint_work_minutes, bd.sprint_break_minutes) == (40, 8)
    assert (bd.body_double_sound, bd.body_double_volume) == ("rain", 20)
    assert store.preferences(family.erin.id, BreaksPreferences).break_extend_minutes == 30
    chart = store.preferences(family.erin.id, ChartPreferences)
    assert (chart.chart_limit, chart.chart_counts_shared) == (1, False)
    husband = store.preferences(family.husband.id, ChartPreferences)
    assert (husband.chart_limit, husband.chart_counts_shared) == (0, True)  # the defaults
