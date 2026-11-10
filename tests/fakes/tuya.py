"""A fake of Tuya's cloud API (32), behind an httpx transport.

    fake_tuya.add_feeder("ebfeeder1", "Cat Feeder")             # standard, plenty of food
    fake_tuya.add_feeder("ebfeeder2", "Mochi's feeder", "fault")  # its own fault bitmap
    fake_tuya.add_feeder("ebfeeder3", "Juneau", "family")  # the family's model, as captured
    fake_tuya.commands["ebfeeder3"]      # what Themi told it: [{"code", "value"}] (F39a)
    fake_tuya.set_status("ebfeeder1", "standard_low")  # a payload in tests/fixtures/tuya
    fake_tuya.fed("ebfeeder1", 2, at)                  # a feeding in its log
    fake_tuya.offline("ebfeeder1")       # the next status read answers 2001
    fake_tuya.limit(times=1)             # the next call answers 1199
    fake_tuya.lapse()                    # the project's plan runs out (28841002)
    fake_tuya.expire_tokens()            # every token it gave stops working (1010)

Every call's signature is checked, with or without a token, like the real one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

from tests.fakes.snapshot import Snapshots
from themi_home.connectors.tuya import TuyaConfig

BASE_URL = "https://tuya.test"
ACCESS_ID = "p9xq7acc3ss1d000"
SECRET = "f4k3s3cr3tf4k3s3cr3tf4k3s3cr3t00"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "tuya"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
FAMILY_MODEL = "drfffce9jdtayqty"  # the family's feeders (captured 2026-11-10)


def payload(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FakeTuya(Snapshots):
    # D5a: what `make dev` would keep between runs
    SNAPSHOT = ("devices", "specs", "statuses", "logs", "keys", "offline_devices", "lapsed")

    def __init__(self) -> None:
        self.devices: dict[str, dict[str, Any]] = {}
        self.specs: dict[str, Any] = {}
        self.statuses: dict[str, Any] = {}
        self.logs: dict[str, list[dict[str, Any]]] = {}
        self.keys = {ACCESS_ID: SECRET}
        self.tokens: dict[str, str] = {}  # access token -> refresh token
        self.calls: list[str] = []
        self.lapsed = False
        self.page_size: int | None = None  # set to page device lists and logs
        self.offline_devices: set[str] = set()
        self.commands: dict[str, list[dict[str, Any]]] = {}  # device -> commands it was sent
        self._limited = 0
        self.transport = httpx.MockTransport(self._handle)

    def config(self) -> TuyaConfig:
        return TuyaConfig(BASE_URL, self.transport)

    # ----- the test's controls ----------------------------------------------------------

    def add_feeder(self, device_id: str, name: str, kind: str = "standard") -> None:
        """A feeder in the linked app account: `kind` "standard" (Tuya's codes, with a food
        level), "fault" (its own fault bitmap) or "family" (the family's own model, from its
        capture: `manual_feed`, no food level)."""
        if kind == "family":
            captured = payload(f"captured/{FAMILY_MODEL}")
            self.add_device(device_id, name, "cwwsq", FAMILY_MODEL)
            self.specs[device_id] = captured["specification"]
            self.statuses[device_id] = captured["status"]
            return
        product = {"standard": "pqxstdfeeder01", "fault": "pqxfaultfeed02"}[kind]
        self.add_device(device_id, name, "cwwsq", product, f"{kind}_spec")
        self.set_status(device_id, "standard_plenty" if kind == "standard" else "fault_none")

    def add_device(
        self, device_id: str, name: str, category: str, product_id: str, spec: str = ""
    ) -> None:
        self.devices[device_id] = {
            "id": device_id,
            "name": name,
            "category": category,
            "product_id": product_id,
            "product_name": "Smart Pet Feeder" if category == "cwwsq" else "Pet Fountain",
            "local_key": "k3yk3yk3yk3yk3yk",
            "online": True,
        }
        self.specs[device_id] = payload(spec) if spec else {"category": category, "status": []}
        self.statuses.setdefault(device_id, [])
        self.logs.setdefault(device_id, [])

    def set_status(self, device_id: str, name: str) -> None:
        self.statuses[device_id] = payload(name)
        self.offline_devices.discard(device_id)

    def fed(self, device_id: str, portions: int, at: datetime) -> None:
        self.logs[device_id].append(
            {
                "code": "feed_report",
                "value": str(portions),
                "event_time": int(at.timestamp() * 1000),
                "event_from": "1",
            }
        )

    def offline(self, device_id: str) -> None:
        self.offline_devices.add(device_id)

    def limit(self, times: int = 1) -> None:
        self._limited += times

    def lapse(self) -> None:
        self.lapsed = True

    def expire_tokens(self) -> None:
        self.tokens.clear()

    # ----- the wire ---------------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        query = dict(parse_qsl(request.url.query.decode()))
        self.calls.append(f"{method} {path}")
        headers = request.headers
        access_id, token = headers.get("client_id", ""), headers.get("access_token", "")
        if headers.get("sign_method") != "HMAC-SHA256" or len(headers.get("t", "")) != 13:
            return _error(1105, "missing the header")
        secret = self.keys.get(access_id)
        if secret is None:
            return _error(1005, "clientId invalid")
        signed = "&".join(f"{k}={v}" for k, v in sorted(query.items()))  # decoded, as Tuya's
        url = path + (f"?{signed}" if signed else "")
        body = hashlib.sha256(request.content).hexdigest() if request.content else EMPTY_SHA256
        to_sign = f"{method}\n{body}\n\n{url}"
        message = f"{access_id}{token}{headers['t']}{headers.get('nonce', '')}{to_sign}"
        expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        if headers.get("sign") != expected.upper():
            return _error(1004, "sign invalid")
        if self._limited:
            self._limited -= 1
            return _error(1199, "your requests are too frequent")
        if path == "/v1.0/token" and query.get("grant_type") == "1":
            return self._new_token()
        if path.startswith("/v1.0/token/"):
            refresh = path.rsplit("/", 1)[1]
            if refresh not in self.tokens.values():
                return _error(1012, "token status is invalid")
            self.tokens = {k: v for k, v in self.tokens.items() if v != refresh}
            return self._new_token()
        if token not in self.tokens:
            return _error(1010, "token is expired")
        if self.lapsed:
            return _error(28841002, "Cloud development plan expired")
        parts = path.strip("/").split("/")
        if path == "/v1.0/iot-01/associated-users/devices":
            return self._page(list(self.devices.values()), query, "devices", "last_row_key")
        if len(parts) == 4 and parts[:2] == ["v1.0", "devices"]:
            device_id, what = parts[2], parts[3]
            if device_id not in self.devices:
                return _error(2010, "device not found")
            if what == "specifications":
                return _ok(self.specs[device_id])
            if what == "status":
                if device_id in self.offline_devices:
                    return _error(2001, "device is offline")
                return _ok(self.statuses[device_id])
            if what == "commands" and method == "POST":
                return self._command(device_id, json.loads(request.content or b"{}"))
            if what == "logs":
                assert query["type"] == "7"
                since, until = int(query["start_time"]), int(query["end_time"])
                codes = set(query.get("codes", "").split(","))
                logs = [
                    entry
                    for entry in self.logs[device_id]
                    if since <= entry["event_time"] <= until and entry["code"] in codes
                ]
                return self._page(logs, query, "logs", "current_row_key", "start_row_key")
        return _error(1108, "uri path invalid")

    def _command(self, device_id: str, body: dict[str, Any]) -> httpx.Response:
        """Like the real one: only a writable data point, only a value in its range."""
        if device_id in self.offline_devices:
            return _error(2001, "device is offline")
        writable = {
            str(f["code"]): f for f in self.specs[device_id].get("functions", []) if "code" in f
        }
        for command in body.get("commands") or []:
            point = writable.get(str(command.get("code")))
            if point is None:
                return _error(2008, "command or value not support")
            if point.get("type") == "Integer":
                bounds = json.loads(point.get("values") or "{}")
                value = command.get("value")
                if not isinstance(value, int) or not bounds.get("min", 0) <= value <= bounds.get(
                    "max", value
                ):
                    return _error(501, "param is illegal")
        self.commands.setdefault(device_id, []).extend(body.get("commands") or [])
        return _ok(True)

    def _new_token(self) -> httpx.Response:
        access, refresh = secrets.token_hex(16), secrets.token_hex(16)
        self.tokens[access] = refresh
        return _ok(
            {"access_token": access, "refresh_token": refresh, "expire_time": 7200, "uid": "u1"}
        )

    def _page(
        self,
        items: list[Any],
        query: dict[str, str],
        name: str,
        key: str,
        asked_key: str | None = None,
    ) -> httpx.Response:
        start = int(query.get(asked_key or key) or 0)
        size = self.page_size or int(query.get("size") or 100)
        chunk = items[start : start + size]
        more = start + size < len(items)
        result = {name: chunk, key: str(start + size) if more else ""}
        result["has_next" if name == "logs" else "has_more"] = more
        return _ok(result)


def _ok(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "result": result, "t": 0, "tid": "x"})


def _error(code: int, msg: str) -> httpx.Response:
    return httpx.Response(200, json={"success": False, "code": code, "msg": msg, "t": 0})


@pytest.fixture
def fake_tuya() -> FakeTuya:
    return FakeTuya()
