"""The MQTT connection for LG ThinQ's pushes, over paho-mqtt (optional: `themi[thinq]`).

AWS IoT's broker wants mutual TLS on port 8883: the certificate LG issued and its key.
Amazon's root CA is in the system's trust store, so nothing else is downloaded. paho runs
its own network thread; each message's bytes go straight to `receive`.

This is the one piece the default test run can't reach: tests use a fake connection.
"""

from __future__ import annotations

import contextlib
import logging
import os
import ssl
import tempfile
from collections.abc import Callable
from typing import Any

from themi_home.connectors.thinq.push import MqttConnect, MqttLogin

log = logging.getLogger(__name__)

PORT = 8883
KEEP_ALIVE = 60


def _paho() -> Any:
    try:
        import paho.mqtt.client as mqtt  # type: ignore[import-not-found]
    except ImportError:
        return None
    return mqtt


def available() -> MqttConnect | None:
    """The real connection, or None without the library (polling alone, then)."""
    return connect if _paho() is not None else None


def _tls(login: MqttLogin) -> ssl.SSLContext:
    context = ssl.create_default_context()
    # load_cert_chain only reads files: the key is on disk (owner-only) just long enough.
    with tempfile.TemporaryDirectory() as folder:
        cert_path, key_path = os.path.join(folder, "cert.pem"), os.path.join(folder, "key.pem")
        with open(cert_path, "w") as f:
            f.write(login.certificate)
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "w") as f:
            f.write(login.private_key.reveal())
        context.load_cert_chain(cert_path, key_path)
    return context


class PahoConnection:
    def __init__(self, client: Any) -> None:
        self._client = client

    def connected(self) -> bool:
        return bool(self._client.is_connected())

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._client.disconnect()
        self._client.loop_stop()


async def connect(login: MqttLogin, receive: Callable[[bytes], None]) -> PahoConnection:
    mqtt = _paho()
    assert mqtt is not None
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=login.client_id, clean_session=False
    )
    client.tls_set_context(_tls(login))

    def on_connect(client: Any, _data: Any, _flags: Any, reason: Any, _props: Any) -> None:
        if reason.is_failure:
            log.warning("LG ThinQ's push server turned the connection down: %s", reason)
            return
        client.subscribe(login.topic, qos=1)  # again after every reconnect

    def on_message(_client: Any, _data: Any, message: Any) -> None:
        receive(bytes(message.payload))

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(login.host, PORT, keepalive=KEEP_ALIVE)
    client.loop_start()  # its thread reconnects on its own after a drop
    return PahoConnection(client)
