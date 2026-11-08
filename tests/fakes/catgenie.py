"""A fake of PetNovations' cloud, where the CatGenie app's litter boxes live (CG1a), behind an
httpx transport.

    fake_catgenie.add_box("CGR0000001", "CatGenie")       # tests/fixtures/catgenie/device.json
    fake_catgenie.set("CGR0000001", sani=15)              # its sani-solution, %
    fake_catgenie.set("CGR0000001", error="HEATER_FAULT") # operationStatus.error
    fake_catgenie.clean("CGR0000001", at)                 # a clean: lastClean, one more cycle
    fake_catgenie.alert("CGR0000001", "DOME_OPEN", at)    # a notification naming an error
    fake_catgenie.filter(times=1)        # the edge's empty 200, as for a client it distrusts
    fake_catgenie.fail(times=1)          # the next call answers 503
    fake_catgenie.expire_tokens()        # every access token stops working (a 401)
    fake_catgenie.revoke()               # the refresh token is refused too: link again

Every call's headers are checked as the app sends them: the hidden time, its version and
`x-render-t`.
"""

from __future__ import annotations

import copy
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fakes.snapshot import Snapshots
from themi import clock
from themi_home.connectors.catgenie import CatGenieConfig
from themi_home.connectors.catgenie.client import render_path, unaes

BASE_URL = "https://catgenie.test"
PHONE = "+15550100123"
CODE = "424242"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "catgenie"


def payload(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FakeCatGenie(Snapshots):
    # D5a: what `make dev` would keep between runs
    SNAPSHOT = ("devices", "notifications", "refresh_tokens", "phones")

    def __init__(self) -> None:
        self.devices: dict[str, dict[str, Any]] = {}
        self.notifications: list[dict[str, Any]] = []
        self.phones = {PHONE}  # the CatGenie accounts there are
        self.codes_sent: list[str] = []  # the phone numbers texted a code
        self.refresh_tokens: set[str] = set()
        self.tokens: dict[str, datetime] = {}  # access token -> when it ends
        self.calls: list[str] = []
        self.rotate = False  # a renewal hands back a new refresh token
        self._filtered = 0
        self._failing = 0
        self.transport = httpx.MockTransport(self._handle)

    def config(self) -> CatGenieConfig:
        return CatGenieConfig(BASE_URL, self.transport)

    # ----- the test's controls ----------------------------------------------------------

    def add_box(self, manufacturer_id: str, name: str) -> None:
        box = payload("device")
        box["manufacturerId"], box["name"] = manufacturer_id, name
        box["macAddress"] = f"{len(self.devices) + 1:012d}"
        self.devices[manufacturer_id] = box

    def set(
        self,
        manufacturer_id: str,
        *,
        sani: int | None = None,
        error: str | None = None,
        active_errors: list[Any] | None = None,
        cleaning: int | None = None,  # % done; -1 back to idle
        online: bool | None = None,
    ) -> None:
        box = self.devices[manufacturer_id]
        if sani is not None:
            box["remainingSaniSolution"] = sani
        if error is not None:
            box["operationStatus"]["error"] = error
        if active_errors is not None:
            box["activeErrors"] = active_errors
        if cleaning is not None:
            idle = cleaning < 0
            box["operationStatus"].update(
                {"state": 0 if idle else 1, "progress": 255 if idle else cleaning}
            )
        if online is not None:
            box["reportedStatus"] = "connected" if online else "disconnected"

    def clean(self, manufacturer_id: str, at: datetime) -> None:
        """A clean finished at `at`: idle again, one more cycle."""
        box = self.devices[manufacturer_id]
        box["lastClean"] = _naive(at)
        box["configuration"]["activation"]["count"] += 1
        box["operationStatus"].update({"state": 0, "progress": 255})

    def alert(self, manufacturer_id: str, error: str, at: datetime, kind: int = 1) -> str:
        """The app is sent a notification about the box, naming `error` ("" for none)."""
        box = self.devices[manufacturer_id]
        alert_id = f"00000000-0000-0000-0000-{len(self.notifications) + 100:012d}"
        data = {
            "errorType": error,
            "parentDeviceId": manufacturer_id,
            "type": kind,
            "version": box["fwVersion"],
            "deviceName": box["name"],
            "deviceId": box["macAddress"],
            "eventTimestamp": _naive(at),
        }
        self.notifications.insert(
            0, {"id": alert_id, "creationTime": _naive(at), "data": json.dumps(data)}
        )
        return alert_id

    def filter(self, times: int = 1) -> None:
        self._filtered += times

    def fail(self, times: int = 1) -> None:
        self._failing += times

    def expire_tokens(self) -> None:
        self.tokens.clear()

    def revoke(self) -> None:
        self.tokens.clear()
        self.refresh_tokens.clear()

    # ----- the wire ---------------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path.lstrip("/"), request.method
        self.calls.append(f"{method} {path}")
        problem = self._headers_wrong(request, path)
        if problem:
            return httpx.Response(400, json={"code": "BAD_HEADERS", "message": problem})
        if self._filtered:
            self._filtered -= 1
            return httpx.Response(200, content=b"")
        if self._failing:
            self._failing -= 1
            return httpx.Response(503, text="Service Unavailable")
        body = json.loads(request.content) if request.content else {}
        if path == "ums/v1/users/generateLoginCode/v2" and method == "POST":
            phone = _phone(body.get("str1", ""))
            if phone in self.phones:
                self.codes_sent.append(phone)
            return httpx.Response(200, content=b"")  # whatever happens, as the real one
        if path == "ums/v1/users/loginByPhoneNumber/v2" and method == "POST":
            phone = _phone(body.get("str1", ""))
            if phone not in self.codes_sent or body.get("code") != CODE:
                return httpx.Response(400, json={"code": "INVALID_CODE", "message": "bad code"})
            self.codes_sent.remove(phone)
            refresh = secrets.token_hex(24)
            self.refresh_tokens.add(refresh)
            access, ends = self._new_token()
            return httpx.Response(
                200,
                json={
                    "userId": "u1",
                    "tenantId": "t1",
                    "accountId": "a1",
                    "accessToken": access,
                    "refreshToken": refresh,
                    "expiration": ends,
                    "phone": phone,
                },
            )
        if path == "facade/v1/mobile-user/refreshToken/v2" and method == "POST":
            if body.get("refreshToken") not in self.refresh_tokens:
                return httpx.Response(401, json={"code": "UNAUTHORIZED", "message": "no"})
            refresh = body["refreshToken"]
            if self.rotate:
                self.refresh_tokens.discard(refresh)
                refresh = secrets.token_hex(24)
                self.refresh_tokens.add(refresh)
            access, ends = self._new_token()
            return httpx.Response(
                200,
                json={
                    "token": access,
                    "refreshToken": refresh,
                    "expiration": str(ends),
                },
            )
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if self.tokens.get(token, clock.now()) <= clock.now():
            return httpx.Response(401, json={"code": "UNAUTHORIZED", "message": "expired"})
        if path == "device/device/v2" and method == "GET":
            assert request.url.params.get("useFleetIndexAndGetRealConnectivity") == "true"
            return httpx.Response(
                200, json={"thingList": copy.deepcopy(list(self.devices.values()))}
            )
        if path == "notification/v1/push/user" and method == "GET":
            return httpx.Response(200, json={"userId": "u1", "notifications": self.notifications})
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": path})

    def _headers_wrong(self, request: httpx.Request, path: str) -> str:
        headers = request.headers
        if headers.get("x-pm-en-ver") != "1.0.0" or headers.get("user-agent") != "okhttp/4.9.2":
            return "missing the app's headers"
        try:
            hidden = unaes(headers.get("x-pm-en-dec", ""))
        except ValueError:
            return "x-pm-en-dec doesn't decrypt"
        ms, _, rest = hidden.partition("-")
        if not ms.isdigit() or (int(ms) // 100) % 2 or len(rest) != 8 or "Z" not in rest:
            return "x-pm-en-dec isn't the time"
        render = headers.get("x-render-t", "")
        stamp = render.rsplit("/", 1)[-1]
        if not render.startswith(f"{render_path(path)}/") or abs(int(ms) - int(stamp)) > 100:
            return "x-render-t doesn't match"
        return ""

    def _new_token(self) -> tuple[str, int]:
        access = (
            "eyJ"
            + secrets.token_hex(12)
            + "."
            + secrets.token_hex(12)
            + "."
            + secrets.token_hex(12)
        )
        ends = clock.now() + timedelta(minutes=30)
        self.tokens[access] = ends
        return access, int(ends.timestamp() * 1000)


def _phone(str1: str) -> str:
    try:
        hidden = unaes(str1)
    except ValueError:
        return ""
    phone, _, rest = hidden.rpartition("-")
    return phone if len(rest) == 8 and "X" in rest else ""


def _naive(at: datetime) -> str:
    """PetNovations' way: UTC, without a zone."""
    return at.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


@pytest.fixture
def fake_catgenie() -> FakeCatGenie:
    return FakeCatGenie()
