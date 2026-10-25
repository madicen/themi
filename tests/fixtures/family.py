"""A seeded family for tests: Erin (admin) and her husband (member).

Use the `family` fixture in any test that needs people; it builds a fresh
in-memory database each time. `seed_family()` does the same for code that
manages its own store (scenario harnesses, scripts).

The husband's real name is set during setup, so the fixture just calls him
"Husband".
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from themi.accounts import SYSTEM, AccountStore, Family, Member, Role
from themi.storage import open_database
from themi.storage.db import Database
from themi.storage.secrets import Cipher, generate_key

ERIN_TELEGRAM_ID = 1001
HUSBAND_TELEGRAM_ID = 1002


@dataclass(frozen=True)
class SeededFamily:
    store: AccountStore
    family: Family
    erin: Member
    husband: Member

    @property
    def db(self) -> Database:
        return self.store.db

    def refresh(self) -> SeededFamily:
        """Re-read both members after a test changed them."""
        return SeededFamily(
            self.store,
            self.store.get_family() or self.family,
            self.store.get_member(self.erin.id),
            self.store.get_member(self.husband.id),
        )


def seed_family(store: AccountStore) -> SeededFamily:
    family = store.create_family(
        "Household",
        "America/Los_Angeles",
        takeout_budget_cents=200_00,
        staples=("olive oil", "eggs", "rice", "coffee", "cat food"),
    )
    erin = store.create_member(SYSTEM, "Erin", Role.ADMIN)
    husband = store.create_member(SYSTEM, "Husband", Role.MEMBER)
    store.update_settings(
        SYSTEM,
        erin.id,
        quiet_start="21:30",
        quiet_end="08:00",
        daily_limit=6,
        pda_strength=2,
        recovery_hours=8,
    )
    store.update_settings(
        SYSTEM,
        husband.id,
        quiet_start="23:00",
        quiet_end="07:00",
        daily_limit=8,
        pda_strength=1,
        recovery_hours=4,
    )
    store.redeem_invite(store.create_invite(SYSTEM, erin.id), ERIN_TELEGRAM_ID)
    store.redeem_invite(store.create_invite(SYSTEM, husband.id), HUSBAND_TELEGRAM_ID)
    return SeededFamily(store, family, store.get_member(erin.id), store.get_member(husband.id))


def make_store() -> AccountStore:
    return AccountStore(open_database(":memory:"), Cipher(generate_key()))


@pytest.fixture
def store() -> AccountStore:
    """An empty, migrated store with no family yet."""
    return make_store()


@pytest.fixture
def family(store: AccountStore) -> SeededFamily:
    return seed_family(store)
