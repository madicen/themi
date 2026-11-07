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


# ----- CR7b1 --------------------------------------------------------------------------


def test_the_second_migration_copies_the_rest(tmp_path: Path) -> None:
    from datetime import time

    from themi.connectors.gcal.preferences import CalendarPreferences
    from themi.core.checkin_reviews import CheckinReviewsPreferences
    from themi.core.conversation_mode import ConversationPreferences
    from themi.core.day_summary import DaySummaryPreferences
    from themi.core.focus import FocusPreferences
    from themi.core.lists import ListsPreferences
    from themi.core.noise_digest import NoisePreferences
    from themi.core.praise import TasksPreferences
    from themi.core.travel import TravelPreferences

    db = Database(tmp_path / "old.db")
    migrations.apply(db, [m for m in migrations.discover() if m.version < 146])
    family = seed_family(AccountStore(db, Cipher(generate_key())))
    db.execute(
        "UPDATE members SET focus_count = 2, day_budget = 4, done_praise = 0, "
        "checkin_reviews = 0, calendar_details = 'partner', calendar_twins = 'guess', "
        "setup_note = 0, morning_summary = '07:15', morning_summary_empty = 1, "
        "getting_ready_minutes = 30, leave_heads_up = 0, noise_emails = 'twice', "
        "conversation_mode = 1, list_style = 'numbers' WHERE id = ?",
        (family.erin.id,),
    )
    migrations.apply(db)
    of = family.store.preferences
    erin = family.erin.id
    assert (of(erin, FocusPreferences).focus_count, of(erin, FocusPreferences).day_budget) == (2, 4)
    assert not of(erin, TasksPreferences).done_praise
    assert not of(erin, CheckinReviewsPreferences).checkin_reviews
    calendar = of(erin, CalendarPreferences)
    assert (calendar.calendar_details, calendar.calendar_twins, calendar.setup_note) == (
        "partner",
        "guess",
        False,
    )
    summary = of(erin, DaySummaryPreferences)
    assert (summary.morning_summary, summary.morning_summary_empty) == (time(7, 15), True)
    travel = of(erin, TravelPreferences)
    assert (travel.getting_ready_minutes, travel.leave_heads_up) == (30, False)
    assert of(erin, NoisePreferences).noise_emails == "twice"
    assert of(erin, ConversationPreferences).conversation_mode
    assert of(erin, ListsPreferences).list_style == "numbers"
    husband = of(family.husband.id, DaySummaryPreferences)
    assert husband.morning_summary is None  # unset copies as off


def test_a_morning_summary_saves_and_reads_back_and_blank_is_off(family: SeededFamily) -> None:
    from datetime import time

    from themi.core.day_summary import DaySummaryPreferences

    store, erin = family.store, family.erin
    store.save_preferences(erin, erin.id, DaySummaryPreferences, morning_summary="08:30")
    assert store.preferences(erin.id, DaySummaryPreferences).morning_summary == time(8, 30)
    store.save_preferences(erin, erin.id, DaySummaryPreferences, morning_summary="")
    assert store.preferences(erin.id, DaySummaryPreferences).morning_summary is None


@pytest.mark.parametrize(
    ("where", "name", "change", "words"),
    [
        ("themi.core.focus", "FocusPreferences", {"focus_count": 0}, "things for now are"),
        ("themi.core.focus", "FocusPreferences", {"day_budget": 21}, "a day's budget is between"),
        (
            "themi.connectors.gcal.preferences",
            "CalendarPreferences",
            {"calendar_details": "all"},
            "calendar details are for 'me' or 'partner'",
        ),
        (
            "themi.connectors.gcal.preferences",
            "CalendarPreferences",
            {"calendar_twins": "both"},
            "ask, guess or keep",
        ),
        ("themi.core.travel", "TravelPreferences", {"getting_ready_minutes": 121}, "getting ready"),
        ("themi.core.noise_digest", "NoisePreferences", {"noise_emails": "hourly"}, "noise emails"),
        ("themi.core.lists", "ListsPreferences", {"list_style": "stars"}, "a list style is"),
        ("themi.core.day_summary", "DaySummaryPreferences", {"morning_summary": "25:00"}, "time"),
    ],
)
def test_the_rest_keep_their_old_words(
    family: SeededFamily, where: str, name: str, change: dict[str, object], words: str
) -> None:
    import importlib

    model = getattr(importlib.import_module(where), name)
    with pytest.raises(InvalidValue, match=words):
        family.store.save_preferences(family.erin, family.erin.id, model, **change)
