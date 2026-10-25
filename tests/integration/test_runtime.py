"""`themi run` end to end: in-process with fakes, and as a real process."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import ERIN_TELEGRAM_ID, SeededFamily
from tests.scenarios.harness import Scenario
from themi.runtime import Runtime
from themi.storage.secrets import generate_key


async def wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.02)


async def test_runtime_serves_health_chats_and_stops_cleanly(
    family: SeededFamily, fake_telegram: FakeTelegram
) -> None:
    scenario = Scenario(family, fake_telegram)  # not started: real time, real polling loop
    runtime = Runtime(
        scenario.app, host="127.0.0.1", port=0, scheduler_tick=timedelta(milliseconds=50)
    )
    task = asyncio.create_task(runtime.run())
    await wait_for(lambda: runtime.port is not None)

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{runtime.port}") as http:
        await wait_for(lambda: scenario.app.channel.last_poll_at is not None)
        health = await http.get("/health")
        assert health.status_code == 200 and health.json()["telegram_poller"] == "alive"

        scenario.primary.queue_text("Hi Erin!")
        fake_telegram.send_text(ERIN_TELEGRAM_ID, "hello")
        await wait_for(lambda: fake_telegram.sent_texts(ERIN_TELEGRAM_ID) == ["Hi Erin!"])

    runtime.stop()
    await asyncio.wait_for(task, timeout=10)
    with pytest.raises(sqlite3.ProgrammingError):  # closed only after everything stopped
        scenario.app.db.scalar("SELECT 1")


async def test_runtime_flushes_the_outbox_on_its_schedule(
    family: SeededFamily, fake_telegram: FakeTelegram
) -> None:
    from themi.channels.outbox import Priority

    scenario = Scenario(family, fake_telegram)
    erin = scenario.member("Erin")
    sender_failures = {"left": 1}
    real_send = scenario.app.channel.send_text

    async def flaky_send(*args: Any, **kwargs: Any) -> int:
        if sender_failures["left"]:
            sender_failures["left"] -= 1
            raise ConnectionError("blip")
        return await real_send(*args, **kwargs)

    scenario.app.outbox.sender.send_text = flaky_send  # type: ignore[method-assign]
    result = await scenario.app.outbox.send(erin, "Washer's done.", priority=Priority.REPLY)
    assert result.status == "queued"
    # Make the retry due immediately rather than in a minute.
    scenario.app.db.execute("UPDATE outbox SET send_after = '2000-01-01T00:00:00+00:00'")

    runtime = Runtime(
        scenario.app,
        host="127.0.0.1",
        port=0,
        telegram_enabled=False,
        scheduler_tick=timedelta(milliseconds=50),
    )
    task = asyncio.create_task(runtime.run())
    await wait_for(lambda: "Washer's done." in fake_telegram.sent_texts(ERIN_TELEGRAM_ID))
    runtime.stop()
    await asyncio.wait_for(task, timeout=10)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_themi_run_as_a_process_starts_and_stops_on_sigterm(tmp_path: Path) -> None:
    """The same check the container smoke test does, without Docker."""
    port = free_port()
    env = {
        **os.environ,
        "THEMI_SECRET_KEY": generate_key(),
        "THEMI_DB_PATH": str(tmp_path / "themi.db"),
        "THEMI_DISABLE_TELEGRAM": "1",
        "THEMI_HTTP_PORT": str(port),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "themi", "run"],
        env=env,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    assert r.status == 200
                    break
            except (urllib.error.URLError, ConnectionError):
                if time.monotonic() > deadline or process.poll() is not None:
                    raise
                time.sleep(0.2)
        process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=20)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 0, stderr
    assert "Stopped" in stderr
    assert (tmp_path / "themi.db").exists()
