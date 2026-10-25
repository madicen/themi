from datetime import datetime, time, timedelta

import pytest

from tests.fixtures.family import ERIN_TELEGRAM_ID, HUSBAND_TELEGRAM_ID, SeededFamily
from themi import clock
from themi.accounts import (
    SYSTEM,
    AccountsError,
    AccountStore,
    InvalidValue,
    InviteError,
    NotFound,
    PermissionDenied,
    Role,
)
from themi.storage.secrets import Secret

# ----- family ---------------------------------------------------------------


def test_family_is_created_once(store: AccountStore) -> None:
    family = store.create_family("Household", "America/Los_Angeles", 150_00, ("eggs",))
    assert (family.name, family.timezone, family.takeout_budget_cents) == (
        "Household",
        "America/Los_Angeles",
        150_00,
    )
    assert family.staples == ("eggs",)
    with pytest.raises(AccountsError, match="already has a family"):
        store.create_family("Again", "UTC")


@pytest.mark.parametrize(("tz", "budget"), [("Mars/Olympus_Mons", 0), ("UTC", -1)])
def test_family_rejects_bad_values(store: AccountStore, tz: str, budget: int) -> None:
    with pytest.raises(InvalidValue):
        store.create_family("Household", tz, budget)


def test_only_admins_update_family(family: SeededFamily) -> None:
    store = family.store
    with pytest.raises(PermissionDenied):
        store.update_family(family.husband, takeout_budget_cents=1)
    updated = store.update_family(
        family.erin, takeout_budget_cents=250_00, staples=(" rice ", "", "beans")
    )
    assert updated.takeout_budget_cents == 250_00
    assert updated.staples == ("rice", "beans")


# ----- members --------------------------------------------------------------


def test_members_need_a_family_first(store: AccountStore) -> None:
    with pytest.raises(AccountsError, match="family"):
        store.create_member(SYSTEM, "Erin", Role.ADMIN)


def test_first_member_comes_from_the_server_and_is_admin(store: AccountStore) -> None:
    store.create_family("Household", "UTC")
    with pytest.raises(InvalidValue, match="admin"):
        store.create_member(SYSTEM, "Erin", Role.MEMBER)
    erin = store.create_member(SYSTEM, "Erin", Role.ADMIN)
    assert erin.is_admin and erin.telegram_user_id is None


def test_only_admins_add_members(family: SeededFamily) -> None:
    with pytest.raises(PermissionDenied):
        family.store.create_member(family.husband, "Guest")
    guest = family.store.create_member(family.erin, "Guest")
    assert guest.role is Role.MEMBER


def test_member_names_are_unique_ignoring_case(family: SeededFamily) -> None:
    with pytest.raises(InvalidValue, match="already a member"):
        family.store.create_member(family.erin, "erin")
    assert family.store.member_by_name("ERIN") == family.erin


def test_new_members_get_sensible_defaults(family: SeededFamily) -> None:
    guest = family.store.create_member(family.erin, "Guest")
    assert guest.quiet_start == time(21, 30) and guest.quiet_end == time(8, 0)
    assert guest.daily_limit == 6
    assert guest.pda_enabled and guest.pda_strength == 2
    assert all(guest.tracking.values())


def test_members_change_only_their_own_settings(family: SeededFamily) -> None:
    store = family.store
    updated = store.update_settings(
        family.erin, family.erin.id, quiet_start="22:15", pda_strength=3, daily_limit=4
    )
    assert updated.quiet_start == time(22, 15)
    assert (updated.pda_strength, updated.daily_limit) == (3, 4)
    with pytest.raises(PermissionDenied):
        store.update_settings(family.erin, family.husband.id, daily_limit=1)


@pytest.mark.parametrize(
    "change",
    [
        {"quiet_start": "late"},
        {"daily_limit": 51},
        {"pda_strength": 4},
        {"recovery_hours": 0.1},
        {"tracking": {"location": True}},
    ],
)
def test_settings_are_validated(family: SeededFamily, change: dict) -> None:
    with pytest.raises(InvalidValue):
        family.store.update_settings(family.erin, family.erin.id, **change)


def test_tracking_toggles_merge(family: SeededFamily) -> None:
    store = family.store
    member = store.update_settings(family.erin, family.erin.id, tracking={"message_timing": False})
    assert not member.tracks("message_timing")
    assert member.tracks("text_notes") and member.tracks("device_activity")
    member = store.update_settings(family.erin, family.erin.id, tracking={"text_notes": False})
    assert not member.tracks("message_timing") and not member.tracks("text_notes")


def test_family_keeps_at_least_one_admin(family: SeededFamily) -> None:
    store = family.store
    with pytest.raises(InvalidValue, match="at least one admin"):
        store.set_role(family.erin, family.erin.id, Role.MEMBER)
    with pytest.raises(InvalidValue, match="at least one admin"):
        store.delete_member(family.erin, family.erin.id)
    store.set_role(family.erin, family.husband.id, Role.ADMIN)
    assert store.set_role(family.husband, family.erin.id, Role.MEMBER).role is Role.MEMBER


def test_only_admins_change_roles_or_delete(family: SeededFamily) -> None:
    with pytest.raises(PermissionDenied):
        family.store.set_role(family.husband, family.husband.id, Role.ADMIN)
    with pytest.raises(PermissionDenied):
        family.store.delete_member(family.husband, family.erin.id)


def test_deleting_a_member_removes_their_data(family: SeededFamily) -> None:
    store = family.store
    husband = family.husband
    store.add_linked_account(husband, husband.id, "gmail", "h@example.com", Secret("tok"))
    store.log_message(husband.id, "in", "hello")
    store.create_invite(family.erin, husband.id)
    store.delete_member(family.erin, husband.id)
    for table in ("linked_accounts", "message_log", "invites"):
        assert (
            store.db.scalar(f"SELECT COUNT(*) FROM {table} WHERE member_id = ?", (husband.id,)) == 0
        )
    with pytest.raises(NotFound):
        store.get_member(husband.id)


# ----- invites --------------------------------------------------------------


@pytest.fixture
def unpaired(family: SeededFamily):
    return family.store.create_member(family.erin, "Guest")


def test_invite_pairs_telegram_once(family: SeededFamily, unpaired) -> None:
    code = family.store.create_invite(family.erin, unpaired.id)
    assert len(code) == 9 and code[4] == "-"
    member = family.store.redeem_invite(code, 2001)
    assert member.id == unpaired.id and member.telegram_user_id == 2001
    assert family.store.member_by_telegram(2001) == member
    with pytest.raises(InviteError):
        family.store.redeem_invite(code, 2001)


def test_invite_codes_tolerate_case_and_spacing(family: SeededFamily, unpaired) -> None:
    code = family.store.create_invite(family.erin, unpaired.id)
    sloppy = code.lower().replace("-", " ")
    assert family.store.redeem_invite(f"  {sloppy} ", 2001).id == unpaired.id


def test_invites_expire_after_24_hours(
    family: SeededFamily, unpaired, frozen_clock: datetime
) -> None:
    code = family.store.create_invite(family.erin, unpaired.id)
    clock.advance(timedelta(hours=24))
    with pytest.raises(InviteError):
        family.store.redeem_invite(code, 2001)


def test_invite_just_before_expiry_still_works(
    family: SeededFamily, unpaired, frozen_clock: datetime
) -> None:
    code = family.store.create_invite(family.erin, unpaired.id)
    clock.advance(timedelta(hours=23, minutes=59))
    assert family.store.redeem_invite(code, 2001).telegram_user_id == 2001


def test_a_new_invite_replaces_the_old_one(family: SeededFamily, unpaired) -> None:
    old = family.store.create_invite(family.erin, unpaired.id)
    new = family.store.create_invite(family.erin, unpaired.id)
    with pytest.raises(InviteError):
        family.store.redeem_invite(old, 2001)
    assert family.store.redeem_invite(new, 2001).id == unpaired.id


def test_only_admins_create_invites(family: SeededFamily, unpaired) -> None:
    with pytest.raises(PermissionDenied):
        family.store.create_invite(family.husband, unpaired.id)


def test_telegram_account_cannot_pair_with_two_members(family: SeededFamily, unpaired) -> None:
    code = family.store.create_invite(family.erin, unpaired.id)
    with pytest.raises(InviteError, match="already paired"):
        family.store.redeem_invite(code, ERIN_TELEGRAM_ID)


def test_unknown_codes_are_rejected(family: SeededFamily) -> None:
    with pytest.raises(InviteError):
        family.store.redeem_invite("AAAA-BBBB", 2001)


def test_only_code_hashes_are_stored(family: SeededFamily, unpaired) -> None:
    code = family.store.create_invite(family.erin, unpaired.id)
    rows = family.store.db.query("SELECT code_hash FROM invites")
    assert all(code.replace("-", "") not in r["code_hash"] for r in rows)


# ----- linked accounts ------------------------------------------------------


def test_members_link_several_gmail_accounts(family: SeededFamily) -> None:
    store, erin = family.store, family.erin
    first = store.add_linked_account(erin, erin.id, "gmail", "Erin@Example.com", Secret("t1"))
    store.add_linked_account(erin, erin.id, "gmail", "erin.work@example.com", Secret("t2"))
    assert first.address == "erin@example.com"
    assert [a.address for a in store.linked_accounts(erin.id)] == [
        "erin@example.com",
        "erin.work@example.com",
    ]
    assert store.linked_accounts(family.husband.id) == []
    assert store.refresh_token(first.id).reveal() == "t1"


def test_refresh_tokens_are_encrypted_in_the_table(family: SeededFamily) -> None:
    erin = family.erin
    account = family.store.add_linked_account(
        erin, erin.id, "gmail", "erin@example.com", Secret("1//plain-refresh-token")
    )
    raw = family.store.db.scalar(
        "SELECT refresh_token FROM linked_accounts WHERE id = ?", (account.id,)
    )
    assert b"plain-refresh-token" not in raw
    family.store.replace_refresh_token(account.id, Secret("1//rotated"))
    assert family.store.refresh_token(account.id).reveal() == "1//rotated"


def test_linked_account_rules(family: SeededFamily) -> None:
    store, erin, husband = family.store, family.erin, family.husband
    with pytest.raises(PermissionDenied):
        store.add_linked_account(husband, erin.id, "gmail", "x@example.com", Secret("t"))
    with pytest.raises(InvalidValue):
        store.add_linked_account(erin, erin.id, "outlook", "x@example.com", Secret("t"))
    with pytest.raises(InvalidValue):
        store.add_linked_account(erin, erin.id, "gmail", "not-an-address", Secret("t"))
    account = store.add_linked_account(erin, erin.id, "gmail", "x@example.com", Secret("t"))
    with pytest.raises(InvalidValue, match="already linked"):
        store.add_linked_account(husband, husband.id, "gmail", "X@example.com", Secret("t"))
    with pytest.raises(PermissionDenied):
        store.remove_linked_account(husband, account.id)
    store.remove_linked_account(erin, account.id)
    assert store.linked_accounts(erin.id) == []


# ----- devices --------------------------------------------------------------


def test_devices_are_admin_managed_with_encrypted_credentials(family: SeededFamily) -> None:
    store = family.store
    with pytest.raises(PermissionDenied):
        store.add_device(family.husband, "lg_thinq", "abc", "Washer")
    washer = store.add_device(
        family.erin, "lg_thinq", "abc", "Washer", "washer", credentials=Secret("pat-123")
    )
    feeder = store.add_device(family.erin, "tuya", "def", "Kitchen feeder")
    assert feeder.appliance is None
    assert store.set_device_appliance(family.erin, feeder.id, "feeder").appliance == "feeder"
    assert store.device_credentials(washer.id) == Secret("pat-123")
    assert store.device_credentials(feeder.id) is None
    raw = store.db.scalar("SELECT credentials FROM devices WHERE id = ?", (washer.id,))
    assert b"pat-123" not in raw
    with pytest.raises(InvalidValue):
        store.set_device_appliance(family.erin, feeder.id, "toaster")
    store.remove_device(family.erin, feeder.id)
    assert [d.name for d in store.list_devices()] == ["Washer"]


# ----- message log ----------------------------------------------------------


def test_recent_messages_are_oldest_first_and_limited(
    family: SeededFamily, frozen_clock: datetime
) -> None:
    store, erin = family.store, family.erin
    for i in range(5):
        store.log_message(erin.id, "in" if i % 2 == 0 else "out", f"m{i}", telegram_message_id=i)
        clock.advance(timedelta(minutes=1))
    store.log_message(family.husband.id, "in", "not erin's")
    recent = store.recent_messages(erin.id, limit=3)
    assert [m.text for m in recent] == ["m2", "m3", "m4"]
    assert [m.direction for m in recent] == ["in", "out", "in"]


# ----- fixture sanity -------------------------------------------------------


def test_seeded_family_is_realistic(family: SeededFamily) -> None:
    assert family.erin.is_admin and not family.husband.is_admin
    assert family.erin.telegram_user_id == ERIN_TELEGRAM_ID
    assert family.husband.telegram_user_id == HUSBAND_TELEGRAM_ID
    assert family.erin.recovery_hours > family.husband.recovery_hours
    assert "cat food" in family.family.staples


def test_permissions_use_current_role_not_a_stale_object(family: SeededFamily) -> None:
    store = family.store
    store.set_role(family.erin, family.husband.id, Role.ADMIN)
    stale_erin = family.erin  # still says admin
    store.set_role(family.husband, family.erin.id, Role.MEMBER)
    with pytest.raises(PermissionDenied):
        store.create_member(stale_erin, "Guest")


def test_busy_times_are_saved_and_checked(family: SeededFamily) -> None:
    from datetime import time

    from themi.accounts import BusyTime

    work = BusyTime((0, 1, 2, 3, 4), time(9), time(17))
    erin = family.store.update_settings(SYSTEM, family.erin.id, busy_times=[work])
    assert family.store.get_member(erin.id).busy_times == (work,)
    assert family.husband.busy_times == ()
    for bad, message in (
        (BusyTime((), time(9), time(17)), "at least one day"),
        (BusyTime((7,), time(9), time(17)), "days of the week"),
        (BusyTime((0,), time(17), time(9)), "end after it starts"),
    ):
        with pytest.raises(InvalidValue, match=message):
            family.store.update_settings(SYSTEM, family.erin.id, busy_times=[bad])
    with pytest.raises(InvalidValue, match="at most 10"):
        family.store.update_settings(SYSTEM, family.erin.id, busy_times=[work] * 11)
    with pytest.raises(PermissionDenied):
        family.store.update_settings(family.husband, family.erin.id, busy_times=[])
