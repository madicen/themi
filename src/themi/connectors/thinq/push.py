"""LG ThinQ's pushes: status changes as they happen, over MQTT (30).

Getting them takes a few steps, as LG's SDK does them:

1. register Themi as a client (`POST /client`, with its kept client id);
2. make a key and a signing request, and trade it for a certificate and a topic;
3. find the broker (`GET /route`), and subscribe each appliance to pushes and events;
4. connect to the broker (AWS IoT, mutual TLS) and subscribe to the topic.

The key and certificate live only in memory: a restart makes new ones. The connection
runs on its own thread and only drops what arrives into a queue; the scheduler's
`devices.thinq_push` job drains it, so everything else stays on the one loop.
Without the MQTT library (`pip install 'themi[thinq]'`), or while it's down, polling
carries on alone.
"""

from __future__ import annotations

import json
import logging
import queue
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from themi import clock
from themi.connectors.thinq.client import ThinqAccount, ThinqError
from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

CLIENT_BODY = {"type": "MQTT", "service-code": "SVC202", "device-type": "607", "allowExist": True}
SERVICE_CODE = "SVC202"
KEY_SIZE = 2048
RETRY_AFTER = timedelta(minutes=15)  # after a failed connection, before the next try


@dataclass(frozen=True)
class MqttLogin:
    host: str
    client_id: str
    topic: str
    certificate: str = field(repr=False)  # PEM
    private_key: Secret = field(repr=False)  # PEM


class MqttConnection(Protocol):
    def connected(self) -> bool: ...

    def close(self) -> None: ...


# Opens a connection that calls `receive` (from any thread) with each message's bytes.
MqttConnect = Callable[[MqttLogin, Callable[[bytes], None]], Awaitable[MqttConnection]]


def signing_request() -> tuple[Secret, str]:
    """(a new private key, PEM; a signing request for it, as LG wants it: base64, no
    header lines)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    request = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "lg_thinq")]))
        .sign(key, hashes.SHA512())
    )
    lines = request.public_bytes(serialization.Encoding.PEM).decode().strip().splitlines()
    return Secret(pem), "".join(lines[1:-1])


class ThinqPush:
    def __init__(self, account: ThinqAccount, connect: MqttConnect | None) -> None:
        self.account = account
        self.connect = connect
        self._connection: MqttConnection | None = None
        self._subscribed: frozenset[str] = frozenset()
        self._retry_at: datetime | None = None
        self._opened_at: datetime | None = None
        self._inbox: queue.SimpleQueue[bytes] = queue.SimpleQueue()

    def connected(self) -> bool:
        return self._connection is not None and self._connection.connected()

    async def keep_up(self, device_ids: list[str]) -> bool:
        """Connect if it isn't, and subscribe any appliance not yet subscribed. Returns
        whether pushes are coming in."""
        if self.connect is None or not self.account.linked() or not device_ids:
            return False
        wanted, now = frozenset(device_ids), clock.now()
        if self._connection is not None and not self.connected():
            if self._opened_at is not None and now < self._opened_at + RETRY_AFTER:
                return False  # still connecting (or reconnecting) on its own
            self.reset()  # it never came up: start over
        if self.connected() and wanted <= self._subscribed:
            return True
        if self._retry_at is not None and now < self._retry_at:
            return False
        try:
            if self.connected():
                await self._subscribe(wanted - self._subscribed)
            else:
                await self._open(wanted)
                self._opened_at = now
        except Exception as exc:  # the broker's library raises what it raises
            log.warning("LG ThinQ pushes aren't connected (%s); polling carries on", exc)
            self.reset()
            self._retry_at = clock.now() + RETRY_AFTER
            return False
        self._retry_at = None
        return self.connected()

    def drain(self) -> list[dict[str, Any]]:
        """Everything pushed since the last drain, oldest first."""
        messages = []
        while True:
            try:
                raw = self._inbox.get_nowait()
            except queue.Empty:
                return messages
            try:
                message = json.loads(raw.decode())
            except (UnicodeDecodeError, ValueError):
                log.warning("LG ThinQ pushed something that isn't JSON; skipped")
                continue
            if isinstance(message, dict):
                messages.append(message)

    def reset(self) -> None:
        """Drop the connection (a new token, an unlink): the next keep_up starts over."""
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                log.warning("The LG ThinQ push connection didn't close cleanly", exc_info=True)
        self._connection, self._subscribed = None, frozenset()
        self._retry_at = self._opened_at = None

    def receive(self, payload: bytes) -> None:
        """Called by the connection, on its own thread."""
        self._inbox.put(payload)

    async def _open(self, device_ids: frozenset[str]) -> None:
        assert self.connect is not None
        client = self.account.client()
        await client.register_client(CLIENT_BODY)
        private_key, csr = signing_request()
        certificate, topic = await client.certificate({"service-code": SERVICE_CODE, "csr": csr})
        host = await client.route()
        if not host:
            raise ThinqError("LG ThinQ didn't say where its push server is")
        await self._subscribe(device_ids)
        self._connection = await self.connect(
            MqttLogin(host, client.client_id, topic, certificate, private_key), self.receive
        )

    async def _subscribe(self, device_ids: frozenset[str]) -> None:
        client = self.account.client()
        for device_id in sorted(device_ids):
            await client.subscribe(device_id)
        self._subscribed |= device_ids
