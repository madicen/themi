"""OV2: the SmartHQ connector against the fake range: signing in (with SmartHQ's emailed
code), kept encrypted; the two ovens; reads; writes that count only when the oven's own
state shows them; Remote Enable; a sign-in that stops working."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from tests.fakes.smarthq import CODE, EMAIL, PASSWORD, FakeSmartHQ
from tests.fixtures.family import SeededFamily
from themi.storage.migrations import apply_track
from themi_home.connectors.smarthq import (
    LOWER,
    UPPER,
    BadCode,
    OvenRefused,
    OvenWatcher,
    SignInLost,
    SmartHQAccount,
    SmartHQError,
)
from themi_home.connectors.smarthq import events as ov

pytestmark = pytest.mark.usefixtures("frozen_clock")
SCHEMA = Path(__file__).resolve().parents[2] / "src" / "themi_home" / "smarthq_schema"


def watcher_for(family: SeededFamily, fake: FakeSmartHQ) -> OvenWatcher:
    apply_track(family.db, "smarthq", SCHEMA)
    return OvenWatcher(SmartHQAccount(family.db, family.store.cipher, fake))


async def linked(family: SeededFamily, fake: FakeSmartHQ) -> OvenWatcher:
    watcher = watcher_for(family, fake)
    assert await watcher.sign_in(family.erin, EMAIL, PASSWORD, "US") is False
    await watcher.submit_code(family.erin, EMAIL, CODE)
    return watcher


async def test_signing_in_by_emailed_code_keeps_the_secrets_encrypted(
    family: SeededFamily, fake_smarthq: FakeSmartHQ, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    watcher = watcher_for(family, fake_smarthq)
    assert await watcher.sign_in(family.erin, " Family@Example.com ", PASSWORD, "us") is False
    assert fake_smarthq.codes_sent == [EMAIL]
    assert not watcher.account.linked()  # not until the code
    with pytest.raises(BadCode):
        await watcher.submit_code(family.erin, EMAIL, "000000")
    await watcher.submit_code(family.erin, EMAIL, f" {CODE} ")  # the same sign-in, again
    row = family.db.one("SELECT * FROM smarthq_account")
    assert row is not None and row["email"] == EMAIL and row["region"] == "US"
    assert row["linked_by"] == family.erin.id
    assert PASSWORD.encode() not in row["password"] and b"rt-2" not in row["refresh_token"]
    assert family.store.cipher.decrypt(row["password"]).reveal() == PASSWORD
    assert PASSWORD not in caplog.text and "rt-2" not in caplog.text
    assert [(o.cavity, o.model) for o in watcher.ovens()] == [
        (UPPER, "CHS950P2M9S1"),
        (LOWER, "CHS950P2M9S1"),
    ]
    # Linking again finds nothing new.
    fake_smarthq.mfa = False
    assert await watcher.sign_in(family.erin, EMAIL, PASSWORD, "US") is True
    assert len(watcher.ovens()) == 2


async def test_a_wrong_password_or_region_isnt_kept(
    family: SeededFamily, fake_smarthq: FakeSmartHQ
) -> None:
    watcher = watcher_for(family, fake_smarthq)
    with pytest.raises(SmartHQError, match="email and password"):
        await watcher.sign_in(family.erin, EMAIL, "wrong", "US")
    with pytest.raises(SmartHQError, match="US or EU"):
        await watcher.sign_in(family.erin, EMAIL, PASSWORD, "Mars")
    with pytest.raises(BadCode, match="ended"):
        await watcher.submit_code(family.erin, EMAIL, CODE)  # no sign-in waiting
    assert not watcher.account.linked()


async def test_reads_keep_the_newest_and_a_rotated_token(
    family: SeededFamily, fake_smarthq: FakeSmartHQ
) -> None:
    watcher = await linked(family, fake_smarthq)
    fake_smarthq.rotate_tokens = True
    assert await watcher.poll() == 2
    upper, lower = watcher.oven(UPPER), watcher.oven(LOWER)
    assert upper is not None and lower is not None
    last = watcher.last(lower)
    assert last is not None and not last.on and last.read_at is not None
    row = family.db.one("SELECT refresh_token FROM smarthq_account")
    assert row is not None
    newest = fake_smarthq.tokens[-1]
    assert family.store.cipher.decrypt(row["refresh_token"]).reveal() == newest


async def test_heat_needs_remote_enable_and_counts_only_when_the_oven_shows_it(
    family: SeededFamily, fake_smarthq: FakeSmartHQ
) -> None:
    watcher = await linked(family, fake_smarthq)
    lower = watcher.oven(LOWER)
    assert lower is not None
    with pytest.raises(OvenRefused, match="Remote Enable is off"):
        await watcher.heat(lower, ov.BAKE, 350, family.erin)
    assert fake_smarthq.writes == []  # not even sent

    fake_smarthq.remote_enable()
    reading = await watcher.heat(lower, ov.BAKE, 350, family.erin)
    assert reading.preheating and reading.set_f == 350
    assert fake_smarthq.writes == [("0x5200", "01015E00000000000000000000")]
    [action] = watcher.actions(lower)
    assert action["what"] == "heat" and action["took"] == 1
    assert action["member_id"] == family.erin.id


async def test_what_each_oven_doesnt_do_is_refused_before_sending(
    family: SeededFamily, fake_smarthq: FakeSmartHQ
) -> None:
    watcher = await linked(family, fake_smarthq)
    upper, lower = watcher.oven(UPPER), watcher.oven(LOWER)
    assert upper is not None and lower is not None
    fake_smarthq.remote_enable()
    cases = [
        (upper, ov.CONV_MULTI_BAKE, 400, "upper oven doesn't do Convection Multi Bake (the lower"),
        (lower, ov.PROOF, 85, "lower oven doesn't do Proof (the upper oven does)"),
        (upper, ov.PROOF, 100, "Proof only runs at 85°F"),
        (lower, ov.BAKE, 600, "170°F to 550°F"),
    ]
    for oven, mode, temp, why in cases:
        with pytest.raises(OvenRefused, match=why.replace("(", r"\(").replace(")", r"\)")):
            await watcher.heat(oven, mode, temp, family.erin)
    assert fake_smarthq.writes == []
    reading = await watcher.heat(upper, ov.PROOF, 85, family.erin)  # OV1's Proof
    assert reading.state == ov.STATE_PROOF


async def test_a_write_the_oven_doesnt_show_is_told_after_30_seconds(
    family: SeededFamily, fake_smarthq: FakeSmartHQ
) -> None:
    watcher = await linked(family, fake_smarthq)
    lower = watcher.oven(LOWER)
    assert lower is not None
    fake_smarthq.remote_enable()
    fake_smarthq.refuse_writes = True  # say Remote Enable lapsed as the write landed
    with pytest.raises(OvenRefused, match="didn't start"):
        await watcher.heat(lower, ov.BAKE, 350, family.erin)
    assert fake_smarthq.settled == 30.0  # waited for the state, not the echoed cook mode
    [action] = watcher.actions(lower)
    assert action["took"] == 0 and action["state_after"] is None


async def test_the_upper_ovens_timer_and_off_without_remote_enable(
    family: SeededFamily, fake_smarthq: FakeSmartHQ
) -> None:
    watcher = await linked(family, fake_smarthq)
    upper, lower = watcher.oven(UPPER), watcher.oven(LOWER)
    assert upper is not None and lower is not None
    reading = await watcher.set_timer(upper, 5, family.erin)
    assert reading.timer_minutes == 5
    with pytest.raises(OvenRefused, match="no kitchen timer"):
        await watcher.set_timer(lower, 5, family.erin)

    fake_smarthq.start_by_hand(UPPER, ov.PROOF, 85)  # started at the range, icon off
    reading = await watcher.off(upper, family.erin)
    assert not reading.on


async def test_a_sign_in_that_stops_working_is_told_once(
    family: SeededFamily, fake_smarthq: FakeSmartHQ
) -> None:
    watcher = await linked(family, fake_smarthq)
    told: list[str] = []

    async def tell(why: str) -> None:
        told.append(why)

    watcher.lost_listeners.append(tell)
    fake_smarthq.expire()
    assert await watcher.poll() == 0
    assert await watcher.poll() == 0  # it waits for linking again
    assert len(told) == 1 and watcher.account.problem()
    lower = watcher.oven(LOWER)
    assert lower is not None
    with pytest.raises(SignInLost):
        await watcher.read(lower)
