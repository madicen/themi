"""A fake of SmartHQ (OV2): the sign-in and the family's range, behind Themi's two seams.

    fake_smarthq.remote_enable()          # Remote Enable pressed on the range
    fake_smarthq.start_by_hand("upper", 13, 85)   # someone starts Proof at the range
    fake_smarthq.set_probe(152)           # the lower oven's probe in, at 152°F
    fake_smarthq.offline = True           # the range doesn't answer until set back
    fake_smarthq.expire()                 # the sign-in stops working
    fake_smarthq.mfa = False              # sign-in doesn't ask for an emailed code
    fake_smarthq.refuse_writes = True     # cook modes echo but never take

It holds the raw ERDs OV1 read from the real range (`tests/fixtures/smarthq`) and behaves
as OV1 found the range does, on `themi.clock`:

- A cook mode is taken only with Remote Enable on, only a mode that oven offers, and Proof
  only at 85°F. A refused one still echoes in the cook mode while the state stays off.
- A taken one preheats at 25°F a minute from the oven's temperature, then cooks; Proof and
  Warm go straight to their state. A cooking oven reports Remote Enable on.
- Off always works, and leaves Remote Enable as it was (OV1).
- The upper oven's kitchen timer runs down, read in whole minutes rounded up.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.snapshot import Snapshots
from themi import clock
from themi_home.connectors.smarthq import BadCode, Range, RangeOffline, SignIn, SignInLost
from themi_home.connectors.smarthq import events as ov

EMAIL = "family@example.com"
PASSWORD = "oven-password-1"
CODE = "246810"
MAC = "D828C9FAKE01"
MODEL = "CHS950P2M9S1"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "smarthq"
HEAT_PER_MINUTE = 25
COOL_PER_MINUTE = 10
ROOM_F = 70
PREHEAT = {ov.BAKE: 1, ov.CONV_BAKE: 2, ov.CONV_MULTI_BAKE: 3, ov.CONV_ROAST: 4}
COOK = {ov.BAKE: 5, ov.CONV_BAKE: 7, ov.CONV_MULTI_BAKE: 9, ov.CONV_ROAST: 11}


def range_off() -> dict[str, str]:
    return json.loads((FIXTURES / "range_off.json").read_text())


class FakeSession:
    def __init__(self, fake: FakeSmartHQ, token: str) -> None:
        self.fake, self.token = fake, token
        self.closed = False

    def _check(self) -> None:
        if self.fake.expired or self.token not in self.fake.tokens:
            raise SignInLost("SmartHQ no longer accepts the sign-in; link it again.")
        if self.fake.offline:
            raise RangeOffline("The range isn't connected right now.")

    async def ranges(self) -> list[Range]:
        self._check()
        return [Range(MAC, MODEL)]

    async def erds(self, mac: str) -> dict[str, str]:
        self._check()
        self.fake.reads += 1
        self.fake.rotate(self)
        return self.fake.erds()

    async def write(self, mac: str, erd: str, value: str) -> None:
        self._check()
        self.fake.receive(erd, value)

    def refresh_token(self) -> str | None:
        return self.token

    async def close(self) -> None:
        self.closed = True


class FakeSmartHQ(Snapshots):
    # D5a: what `make dev` keeps between runs
    SNAPSHOT = ("raw", "ovens", "remote", "timer_until", "probe_f", "tokens", "expired")

    def __init__(self) -> None:
        self.raw = range_off()
        # Per oven: its mode, set °F, state, and the °F it was at `since` (heating or not).
        self.ovens: dict[str, dict[str, Any]] = {
            c: {"mode": 0, "set_f": 0, "state": 0, "from_f": ROOM_F, "since": None}
            for c in ov.CAVITIES
        }
        self.remote = False  # Remote Enable, pressed on the range (both ovens)
        self.timer_until: datetime | None = None
        self.probe_f: int | None = None
        self.tokens = ["rt-1"]
        self.expired = False
        self.offline = False
        self.mfa = True
        self.rotate_tokens = False
        self.refuse_writes = False  # the range drops cook modes (echoed, never taken)
        self.codes_sent: list[str] = []
        self.writes: list[tuple[str, str]] = []
        self.sessions: list[FakeSession] = []
        self.reads = 0
        self.settled = 0.0

    # ----- the seam (SmartHQLogin) ----------------------------------------------------

    async def sign_in(self, email: str, password: str, region: str) -> SignIn:
        if email != EMAIL or password != PASSWORD:
            from themi_home.connectors.smarthq import SmartHQError

            raise SmartHQError("SmartHQ didn't accept that email and password.")
        self.expired = False
        if self.mfa:
            self.codes_sent.append(email)
            return SignIn(code_sent=True)
        return SignIn(token=self._new_token())

    async def submit_code(self, email: str, code: str) -> str:
        if email not in self.codes_sent or code != CODE:
            raise BadCode("That code didn't work; check it, or start again.")
        return self._new_token()

    async def open(self, email: str, region: str, refresh_token: str) -> FakeSession:
        if self.expired or refresh_token not in self.tokens:
            raise SignInLost("SmartHQ no longer accepts the sign-in; link it again.")
        session = FakeSession(self, refresh_token)
        self.sessions.append(session)
        return session

    async def settle(self, seconds: float) -> None:
        self.settled += seconds
        if clock.is_frozen():
            clock.advance(timedelta(seconds=seconds))

    # ----- the range --------------------------------------------------------------------

    def erds(self) -> dict[str, str]:
        """The raw ERDs as the range would report them now."""
        now = clock.now()
        raw = dict(self.raw)
        for cavity in ov.CAVITIES:
            o = self._settle_oven(cavity, now)
            raw[ov.code(cavity, ov.CURRENT_STATE)] = f"{o['state']:02X}"
            if o["state"] == 0:
                raw.setdefault(ov.code(cavity, ov.COOK_MODE), ov.OFF_VALUE)
            raw[ov.code(cavity, ov.RAW_TEMPERATURE)] = f"{self._temp(cavity, now):04X}"
            cooking = o["state"] != 0
            raw[ov.code(cavity, ov.REMOTE_ENABLED)] = "01" if self.remote or cooking else "00"
        left = 0
        if self.timer_until is not None and self.timer_until > now:
            left = math.ceil((self.timer_until - now).total_seconds() / 60)
        raw[ov.code(ov.UPPER, ov.KITCHEN_TIMER)] = ov.timer_value(left)
        if self.probe_f is not None:
            raw[ov.code(ov.LOWER, ov.PROBE_PRESENT)] = "01"
            raw[ov.code(ov.LOWER, ov.PROBE_DISPLAY_TEMP)] = f"{self.probe_f:04X}"
        else:
            raw[ov.code(ov.LOWER, ov.PROBE_PRESENT)] = "00"
            raw[ov.code(ov.LOWER, ov.PROBE_DISPLAY_TEMP)] = "0000"
        return raw

    def receive(self, erd: str, value: str) -> None:
        self.writes.append((erd, value))
        for cavity in ov.CAVITIES:
            if erd == ov.code(cavity, ov.COOK_MODE):
                self._cook(cavity, value)
                return
        if erd == ov.code(ov.UPPER, ov.KITCHEN_TIMER):
            minutes = int(value, 16)
            self.timer_until = clock.now() + timedelta(minutes=minutes) if minutes else None
            return
        self.raw[erd] = value

    def _cook(self, cavity: str, value: str) -> None:
        now = clock.now()
        mode, set_f = int(value[0:2], 16), int(value[2:6], 16)
        o = self.ovens[cavity]
        temp = self._temp(cavity, now)
        if mode == ov.OFF:
            o.update(mode=0, set_f=0, state=0, from_f=temp, since=now)
            self.raw[ov.code(cavity, ov.COOK_MODE)] = ov.OFF_VALUE
            return
        self.raw[ov.code(cavity, ov.COOK_MODE)] = value  # echoed, taken or not
        cooking = o["state"] != 0
        if not (self.remote or cooking) or not self._takes(cavity, mode, set_f):
            return
        if self.refuse_writes:
            return
        self._start(cavity, mode, set_f, now)

    def _takes(self, cavity: str, mode: int, set_f: int) -> bool:
        if mode not in ov.OFFERS[cavity]:
            return False
        if mode == ov.PROOF:
            return set_f == ov.PROOF_F
        return ov.LOWEST_F <= set_f <= ov.HIGHEST_F

    def _start(
        self, cavity: str, mode: int, set_f: int, now: datetime, probe_target_f: int = 0
    ) -> None:
        o = self.ovens[cavity]
        temp = self._temp(cavity, now)
        state = ov.STATE_PROOF if mode == ov.PROOF else PREHEAT.get(mode, 1)
        o.update(mode=mode, set_f=set_f, state=state, from_f=temp, since=now)
        value = ov.cook_value(mode, set_f)
        if probe_target_f:  # set on the range: the cook mode's probe field
            value = value[:10] + f"{probe_target_f:04X}" + value[14:]
        self.raw[ov.code(cavity, ov.COOK_MODE)] = value

    def _settle_oven(self, cavity: str, now: datetime) -> dict[str, Any]:
        """A preheating oven that's reached its °F moves on to cooking."""
        o = self.ovens[cavity]
        if o["state"] in ov.PREHEATING and self._temp(cavity, now) >= o["set_f"]:
            o["state"] = COOK.get(o["mode"], 5)
        return o

    def _temp(self, cavity: str, now: datetime) -> int:
        o = self.ovens[cavity]
        if o["since"] is None:
            return ROOM_F
        minutes = (now - o["since"]).total_seconds() / 60
        if o["state"] == 0:
            return max(ROOM_F, int(o["from_f"] - COOL_PER_MINUTE * minutes))
        target = ov.PROOF_F if o["mode"] == ov.PROOF else o["set_f"]
        return min(target, int(o["from_f"] + HEAT_PER_MINUTE * minutes))

    def rotate(self, session: FakeSession) -> None:
        if self.rotate_tokens:
            session.token = self._new_token()

    def _new_token(self) -> str:
        token = f"rt-{len(self.tokens) + 1}"
        self.tokens.append(token)
        return token

    # ----- test controls ----------------------------------------------------------------

    def remote_enable(self, on: bool = True) -> None:
        self.remote = on

    def start_by_hand(self, cavity: str, mode: int, set_f: int, *, probe_target_f: int = 0) -> None:
        """Started at the range: no Remote Enable needed (and a probe target, if given)."""
        self._start(cavity, mode, set_f, clock.now(), probe_target_f)

    def preheated(self, cavity: str) -> None:
        """Skip to the oven at its temperature."""
        o = self.ovens[cavity]
        o["from_f"], o["since"] = o["set_f"], clock.now()
        o["state"] = COOK.get(o["mode"], o["state"]) if o["state"] in ov.PREHEATING else o["state"]

    def set_probe(self, temp_f: int | None) -> None:
        self.probe_f = temp_f

    def state(self, cavity: str) -> int:
        return self._settle_oven(cavity, clock.now())["state"]

    def expire(self) -> None:
        self.expired = True


@pytest.fixture
def fake_smarthq() -> FakeSmartHQ:
    return FakeSmartHQ()
