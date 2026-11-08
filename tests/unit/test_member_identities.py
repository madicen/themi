"""CR20a2: how each member is reached on each channel, in member_identities."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.family import ERIN_TELEGRAM_ID, HUSBAND_TELEGRAM_ID, SeededFamily
from themi import clock
from themi.accounts import SYSTEM, AccountStore, InviteError, Role
from themi.storage import migrations
from themi.storage.db import Database
from themi.storage.secrets import Cipher, generate_key


def test_the_migration_copies_each_telegram_id_and_empties_the_old_column(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "old.db")
    migrations.apply(db, [m for m in migrations.discover() if m.version < 150])
    now = clock.now().isoformat()
    for member_id, name, telegram in ((1, "Erin", 1001), (2, "Husband", None)):
        db.execute(
            "INSERT INTO members (id, name, role, telegram_user_id, created_at, updated_at) "
            "VALUES (?, ?, 'admin', ?, ?, ?)",
            (member_id, name, telegram, now, now),
        )
    migrations.apply(db)
    rows = db.query("SELECT member_id, channel, external_id FROM member_identities")
    assert [(r["member_id"], r["channel"], r["external_id"]) for r in rows] == [
        (1, "telegram", "1001")
    ]
    assert db.scalar("SELECT COUNT(*) FROM members WHERE telegram_user_id IS NOT NULL") == 0
    store = AccountStore(db, Cipher(generate_key()))
    assert store.get_member(1).telegram_user_id == 1001
    assert store.get_member(2).telegram_user_id is None


def test_lookups_by_channel(family: SeededFamily) -> None:
    store, erin = family.store, family.erin
    assert store.member_by_identity("telegram", str(ERIN_TELEGRAM_ID)) == erin
    assert store.member_by_telegram(HUSBAND_TELEGRAM_ID) == family.husband
    assert store.identity(erin.id, "telegram") == str(ERIN_TELEGRAM_ID)
    assert store.member_by_identity("web", "erin") is None
    store.set_identity(erin.id, "web", "erin")  # on a second channel too
    assert store.identities(erin.id) == {"telegram": str(ERIN_TELEGRAM_ID), "web": "erin"}
    assert store.member_by_identity("web", "erin") == store.get_member(erin.id)


def test_pairing_writes_an_identity_and_one_account_is_one_member(family: SeededFamily) -> None:
    store = family.store
    guest = store.create_member(SYSTEM, "Guest", Role.MEMBER)
    assert store.identities(guest.id) == {}
    store.redeem_invite(store.create_invite(SYSTEM, guest.id), 3003)
    assert store.identities(guest.id) == {"telegram": "3003"}
    other = store.create_member(SYSTEM, "Other", Role.MEMBER)
    with pytest.raises(InviteError, match="already paired"):
        store.redeem_invite(store.create_invite(SYSTEM, other.id), 3003)


def test_a_member_removed_takes_their_identities(family: SeededFamily) -> None:
    store = family.store
    guest = store.create_member(SYSTEM, "Guest", Role.MEMBER)
    store.redeem_invite(store.create_invite(SYSTEM, guest.id), 3004)
    store.delete_member(SYSTEM, guest.id)
    assert store.member_by_telegram(3004) is None
