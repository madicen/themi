"""A fake of Roborock (V1): the sign-in and the robots, behind Themi's two seams.

    fake_roborock.add_robot("rr-duid-1", "Robbie")
    fake_roborock.set_status("rr-duid-1", "trapped")   # a payload in tests/fixtures/roborock
    fake_roborock.rooms["rr-duid-1"] = "Kitchen"       # where its map puts it
    fake_roborock.set_parts("rr-duid-1", filter_work_time=530_000)
    fake_roborock.offline("rr-duid-1")                 # it doesn't answer until set again
    fake_roborock.expire()                             # the sign-in stops working

Like the real robot, "Resolved" clears its alert (a dock's water alert stays until then),
and "go home" sets it heading home.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.snapshot import Snapshots
from themi.connectors.roborock import (
    BadCode,
    LoginExpired,
    RobotOffline,
    VacuumDevice,
)

EMAIL = "family@example.com"
CODE = "123456"
SECRET_TOKEN = "rr-secret-token-abc"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "roborock"


def payload(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FakeSession:
    def __init__(self, fake: FakeRoborock, login: dict[str, Any]) -> None:
        self.fake, self.login = fake, login
        self.closed = False

    def _check(self) -> None:
        if self.fake.expired or self.login["user_data"]["token"] != self.fake.token:
            raise LoginExpired("Roborock no longer accepts the sign-in; link it again.")

    def _robot(self, duid: str) -> dict[str, Any]:
        self._check()
        if duid in self.fake.offline_robots:
            raise RobotOffline("The vacuum isn't connected right now.")
        return self.fake.statuses[duid]

    async def devices(self) -> list[VacuumDevice]:
        self._check()
        return list(self.fake.robots.values())

    async def status(self, duid: str) -> dict[str, Any]:
        self.fake.reads += 1
        return dict(self._robot(duid))

    async def consumables(self, duid: str) -> dict[str, int]:
        self._robot(duid)
        return dict(self.fake.parts[duid])

    async def room(self, duid: str) -> str | None:
        self._robot(duid)
        self.fake.room_reads += 1
        return self.fake.rooms.get(duid)

    async def resolve(self, duid: str, code: int) -> None:
        status = self._robot(duid)
        self.fake.resolved.append((duid, code))
        if status.get("dock_error_status") == code:
            status["dock_error_status"] = 0
            status["dss"] = 169
        elif status.get("error_code") == code:
            status["error_code"] = 0
            status["state"] = 3  # idle, wherever it stopped

    async def send_home(self, duid: str) -> None:
        status = self._robot(duid)
        self.fake.sent_home.append(duid)
        status["state"] = 6

    async def close(self) -> None:
        self.closed = True


class FakeRoborock(Snapshots):
    # D5a: what `make dev` keeps between runs
    SNAPSHOT = (
        "robots",
        "statuses",
        "parts",
        "rooms",
        "offline_robots",
        "codes_sent",
        "token",
        "expired",
    )

    def __init__(self) -> None:
        self.robots: dict[str, VacuumDevice] = {}
        self.statuses: dict[str, dict[str, Any]] = {}
        self.parts: dict[str, dict[str, int]] = {}
        self.rooms: dict[str, str] = {}
        self.offline_robots: set[str] = set()
        self.codes_sent: list[str] = []
        self.resolved: list[tuple[str, int]] = []
        self.sent_home: list[str] = []
        self.sessions: list[FakeSession] = []
        self.token = SECRET_TOKEN
        self.expired = False
        self.reads = 0
        self.room_reads = 0

    # ----- the seam (RoborockLogin) ---------------------------------------------------

    async def request_code(self, email: str) -> None:
        self.codes_sent.append(email)

    async def code_login(self, email: str, code: str) -> dict[str, Any]:
        if email not in self.codes_sent or code != CODE:
            raise BadCode("That code didn't work; ask for a new one.")
        self.expired = False
        return {"user_data": {"token": self.token, "rruid": "rr-user"}, "base_url": "https://x"}

    async def open(self, email: str, login: dict[str, Any]) -> FakeSession:
        session = FakeSession(self, login)
        self.sessions.append(session)
        return session

    # ----- test controls ------------------------------------------------------------------

    def add_robot(self, duid: str, name: str, model: str = "roborock.vacuum.a97") -> None:
        self.robots[duid] = VacuumDevice(duid, name, model)
        self.statuses[duid] = payload("docked")
        self.parts[duid] = payload("consumables")

    def set_status(self, duid: str, name: str, **changes: Any) -> None:
        self.offline_robots.discard(duid)
        self.statuses[duid] = {**payload(name), **changes}

    def set_parts(self, duid: str, **counters: int) -> None:
        self.parts[duid] = {**self.parts[duid], **counters}

    def offline(self, duid: str) -> None:
        self.offline_robots.add(duid)

    def expire(self) -> None:
        self.expired = True


@pytest.fixture
def fake_roborock() -> FakeRoborock:
    return FakeRoborock()
