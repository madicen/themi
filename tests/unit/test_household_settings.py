"""CR7c: the household's settings that belong to one module, and the old columns gone."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.family import SeededFamily
from themi.accounts import AccountStore, InvalidValue
from themi.accounts.store import PermissionDenied
from themi.storage import migrations
from themi.storage.db import Database
from themi.storage.secrets import Cipher, generate_key
from themi_home.body_double import BodyDoublePreferences
from themi_home.laundry import LaundrySettings
from themi_home.pantry import PantrySettings
from themi_home.spending import SpendingSettings


def columns(db: Database, table: str) -> set[str]:
    return {r["name"] for r in db.query(f"PRAGMA table_info({table})")}


from tests.unit.test_member_preferences import old_family  # noqa: E402


def test_an_existing_database_keeps_every_value(tmp_path: Path) -> None:
    db = Database(tmp_path / "old.db")
    migrations.apply(db, [m for m in migrations.discover() if m.version < 145])
    store = AccountStore(db, Cipher(generate_key()))
    erin = old_family(store).erin
    db.execute(
        'UPDATE family SET takeout_budget_cents = 300, staples = \'["eggs", "rice"]\', '
        "laundry_fresh_hours = 6.5, laundry_rinse_minutes = 25"
    )
    db.execute("UPDATE members SET sprint_work_minutes = 40 WHERE id = ?", (erin.id,))
    migrations.apply(db)
    assert store.household(SpendingSettings).takeout_budget_cents == 300
    assert store.household(PantrySettings).staples == ("eggs", "rice")
    laundry = store.household(LaundrySettings)
    assert (laundry.laundry_fresh_hours, laundry.laundry_rinse_minutes) == (6.5, 25)
    assert store.preferences(erin.id, BodyDoublePreferences).sprint_work_minutes == 40


def test_the_moved_columns_are_gone(family: SeededFamily) -> None:
    moved_from_members = {
        "sprint_work_minutes", "chart_limit", "focus_count", "done_praise", "calendar_details",
        "morning_summary", "noise_emails", "conversation_mode", "list_style",
    }  # fmt: skip
    assert not moved_from_members & columns(family.db, "members")
    assert {"listen_first", "day_ends", "quiet_start"} <= columns(family.db, "members")
    assert not {"takeout_budget_cents", "staples", "laundry_fresh_hours"} & columns(
        family.db, "family"
    )
    assert {"task_owners", "handover_cost"} <= columns(family.db, "family")  # the energy model's


def test_household_settings_are_for_admins(family: SeededFamily) -> None:
    with pytest.raises(PermissionDenied):
        family.store.save_household(family.husband, LaundrySettings, laundry_fresh_hours=4)
    family.store.save_household(family.erin, LaundrySettings, laundry_fresh_hours=4)
    assert family.store.household(LaundrySettings).laundry_fresh_hours == 4


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"laundry_fresh_hours": 0.5}, "a wet load stays fresh for 1 to 48 hours"),
        ({"laundry_rinse_minutes": 181}, "a rewash takes 5 to 180 minutes"),
    ],
)
def test_the_laundry_checks_keep_their_words(
    family: SeededFamily, change: dict[str, object], words: str
) -> None:
    with pytest.raises(InvalidValue, match=words):
        family.store.save_household(family.erin, LaundrySettings, **change)


def test_first_run_setup_can_set_one_before_any_module_is_loaded(family: SeededFamily) -> None:
    family.store.set_household_value("spending", "takeout_budget_cents", 123)
    assert family.store.household(SpendingSettings).takeout_budget_cents == 123
