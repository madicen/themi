"""A fake of LG's ThinQ Connect API (30), behind an httpx transport, with a fake MQTT broker.

    fake_thinq.add_device("lg-washer-1", "DEVICE_WASHER", "Washer")
    fake_thinq.set_state("lg-washer-1", "washer_running")  # a payload in tests/fixtures/thinq
    fake_thinq.set_run_state("lg-washer-1", "END")          # or just the run state
    fake_thinq.offline("lg-washer-1")      # the next state read answers 1222
    fake_thinq.limit(times=1)              # the next call answers 1306
    fake_thinq.revoke()                    # the token stops working
    fake_thinq.push(message)               # the broker delivers a message (once connected)

The token, country and LG's headers are checked on every call, like the real one.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fakes.snapshot import Snapshots
from themi.connectors.thinq import MqttLogin, ThinqConfig
from themi.connectors.thinq.client import API_KEY

BASE_URL = "https://thinq.test"
TOKEN = "thinqpat_family_token"
MQTT_HOST = "a3abcd1234-ats.iot.us-west-2.amazonaws.com"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "thinq"


def payload(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FakeMqtt:
    def __init__(self, fake: FakeThinq, login: MqttLogin, receive: Callable[[bytes], None]):
        self.fake, self.login, self.receive = fake, login, receive
        self.up = fake.broker_up
        self.closed = False

    def connected(self) -> bool:
        return self.up and not self.closed

    def close(self) -> None:
        self.closed = True


class FakeThinq(Snapshots):
    # D5a: what `make dev` keeps between runs
    SNAPSHOT = (
        "devices",
        "states",
        "tokens",
        "clients",
        "subscribed",
        "certificates",
        "broker_up",
        "_offline",
    )

    def __init__(self) -> None:
        self.devices: dict[str, dict[str, Any]] = {}
        self.states: dict[str, Any] = {}
        self.tokens = {TOKEN}
        self.calls: list[str] = []
        self.clients: set[str] = set()
        self.subscribed: set[str] = set()
        self.certificates = 0
        self.connections: list[FakeMqtt] = []
        self.broker_up = True  # new connections come up straight away
        self._offline: set[str] = set()
        self._limited = 0
        self.transport = httpx.MockTransport(self._handle)

    def config(self, *, pushes: bool = True) -> ThinqConfig:
        return ThinqConfig(BASE_URL, self.transport, self.connect if pushes else None)

    # ----- the test's controls ----------------------------------------------------------

    def add_device(self, device_id: str, kind: str, alias: str, model: str = "WM4000HWA") -> None:
        self.devices[device_id] = {
            "deviceId": device_id,
            "deviceInfo": {"deviceType": kind, "modelName": model, "alias": alias},
        }
        initial = {"DEVICE_WASHER": "washer_power_off", "DEVICE_DRYER": "dryer_initial"}
        self.states[device_id] = payload(initial.get(kind, "dryer_initial"))

    def set_state(self, device_id: str, name: str) -> None:
        self.states[device_id] = payload(name)
        self._offline.discard(device_id)

    def set_run_state(self, device_id: str, word: str) -> None:
        kind = self.devices[device_id]["deviceInfo"]["deviceType"]
        state = {"runState": {"currentState": word}}
        self.states[device_id] = (
            [{"location": {"locationName": "MAIN"}, **state}]
            if (kind == "DEVICE_WASHER")
            else state
        )
        self._offline.discard(device_id)

    def offline(self, device_id: str) -> None:
        self._offline.add(device_id)

    def limit(self, times: int = 1) -> None:
        self._limited += times

    def revoke(self) -> None:
        self.tokens.clear()

    def push(self, message: dict[str, Any]) -> None:
        """The broker hands a message to every open connection."""
        live = [c for c in self.connections if c.connected()]
        assert live, "nothing is connected to the fake broker"
        for connection in live:
            connection.receive(json.dumps(message).encode())

    def push_state(self, device_id: str, word: str) -> None:
        kind = self.devices[device_id]["deviceInfo"]["deviceType"]
        self.push(
            {
                "pushType": "DEVICE_STATUS",
                "deviceId": device_id,
                "deviceType": kind,
                "report": [
                    {"location": {"locationName": "MAIN"}, "runState": {"currentState": word}}
                ]
                if kind == "DEVICE_WASHER"
                else {"runState": {"currentState": word}},
            }
        )

    async def connect(self, login: MqttLogin, receive: Callable[[bytes], None]) -> FakeMqtt:
        assert login.host == MQTT_HOST
        assert login.client_id in self.clients
        assert "BEGIN PRIVATE KEY" in login.private_key.reveal()
        connection = FakeMqtt(self, login, receive)
        self.connections.append(connection)
        return connection

    # ----- the wire ---------------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append(f"{method} {path}")
        headers = request.headers
        if headers.get("x-api-key") != API_KEY or not headers.get("x-message-id"):
            return _error(400, "1216", "Incorrect header")
        if headers.get("x-country") != "US":
            return _error(400, "1307", "Not supported country")
        if self._limited:
            self._limited -= 1
            return _error(429, "1306", "Exceeded API calls")
        if headers.get("Authorization", "").removeprefix("Bearer ") not in self.tokens:
            return _error(401, "1218", "Invalid token")
        client_id = headers.get("x-client-id", "")
        body = json.loads(request.content) if request.content else None
        parts = path.strip("/").split("/")
        if (method, path) == ("GET", "/devices"):
            return _ok(list(self.devices.values()))
        if method == "GET" and len(parts) == 3 and parts[0] == "devices" and parts[2] == "state":
            device_id = parts[1]
            if device_id not in self.devices:
                return _error(404, "1205", "Not exist device")
            if device_id in self._offline:
                return _error(400, "1222", "Not connected device")
            return _ok(self.states[device_id])
        if (method, path) == ("POST", "/client"):
            assert body and body["type"] == "MQTT"
            self.clients.add(client_id)
            return _ok({})
        if (method, path) == ("POST", "/client/certificate"):
            assert client_id in self.clients and body and body["csr"]
            self.certificates += 1
            pem = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"
            topic = f"app/clients/{client_id}/push"
            return _ok({"result": {"certificatePem": pem, "subscriptions": [topic]}})
        if (method, path) == ("GET", "/route"):
            return _ok({"apiServer": BASE_URL, "mqttServer": f"mqtts://{MQTT_HOST}:8883"})
        if method == "POST" and len(parts) == 3 and parts[0] in ("push", "event"):
            key = f"{parts[0]}:{parts[1]}"
            if key in self.subscribed:
                return _error(400, "1207", "Already subscribed push")
            self.subscribed.add(key)
            return _ok({})
        return _error(404, "1000", "Bad request")


def _ok(response: Any) -> httpx.Response:
    message_id = secrets.token_urlsafe(16)
    return httpx.Response(200, json={"messageId": message_id, "response": response})


def _error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


@pytest.fixture
def fake_thinq() -> FakeThinq:
    return FakeThinq()
