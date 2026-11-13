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
from themi.runtime import PortInUse, Runtime
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
    assert f"Themi is running at http://localhost:{port}" in stderr  # where to open it
    assert f"Open its website (http://localhost:{port})" in stderr  # with the claim code
    assert (tmp_path / "themi.db").exists()


def test_themi_run_on_a_port_in_use_says_so_and_stops(tmp_path: Path) -> None:
    """Another Themi (or anything) on the port: one plain line, no tracebacks, exit 1."""
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        process = subprocess.run(
            [sys.executable, "-m", "themi", "run"],
            env={
                **os.environ,
                "THEMI_SECRET_KEY": generate_key(),
                "THEMI_DB_PATH": str(tmp_path / "themi.db"),
                "THEMI_DISABLE_TELEGRAM": "1",
                "THEMI_HTTP_PORT": str(port),
            },
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert process.returncode == 1, process.stderr
    assert f"Port {port} is already in use" in process.stderr
    assert "THEMI_HTTP_PORT" in process.stderr
    assert "Traceback" not in process.stderr and "Themi is running" not in process.stderr


async def test_a_port_in_use_stops_the_runtime_before_anything_starts(
    scenario: Scenario,
) -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        runtime = Runtime(scenario.app, host="127.0.0.1", port=port, telegram_enabled=False)
        with pytest.raises(PortInUse, match=f"Port {port} is already in use"):
            await runtime.run()
    assert scenario.app.scheduler is not None
    assert not runtime.stop_event.is_set()  # it never started, so there's nothing to stop


async def test_a_restart_from_the_modules_page_stops_themi_to_start_again(
    family: SeededFamily, fake_telegram: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SP6: the runtime stops as on SIGTERM and says to start again; the caller re-executes."""
    from themi import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "RESTART_AFTER_SECONDS", 0)
    scenario = Scenario(family, fake_telegram)
    runtime = Runtime(scenario.app, host="127.0.0.1", port=0, telegram_enabled=False)
    task = asyncio.create_task(runtime.run())
    await wait_for(lambda: runtime.server.started)
    assert scenario.app.services.restart is not None
    scenario.app.services.restart()
    await asyncio.wait_for(task, timeout=10)
    assert runtime.restart_requested


async def test_stopping_closes_what_the_modules_opened_before_the_database(
    family: SeededFamily, fake_telegram: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connection a module keeps open (the vacuum's MQTT session) is closed on the way
    out. One that won't close is left after a few seconds, and the rest still close."""
    from themi import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "CLOSE_TIMEOUT_SECONDS", 0.05)
    scenario = Scenario(family, fake_telegram)
    closed: list[str] = []

    async def hangs() -> None:
        await asyncio.Event().wait()

    async def fails() -> None:
        raise ConnectionError("already gone")

    async def closes() -> None:
        scenario.app.db.scalar("SELECT 1")  # the database is still open for it
        closed.append("vacuum")

    scenario.app.services.closers += [("hangs", hangs), ("fails", fails), ("vacuum", closes)]
    runtime = Runtime(scenario.app, host="127.0.0.1", port=0, telegram_enabled=False)
    task = asyncio.create_task(runtime.run())
    await wait_for(lambda: runtime.server.started)
    runtime.stop()
    await asyncio.wait_for(task, timeout=10)
    assert closed == ["vacuum"]
    with pytest.raises(sqlite3.ProgrammingError):
        scenario.app.db.scalar("SELECT 1")


def test_a_task_that_ignores_being_cancelled_cant_keep_themi_from_stopping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """13 Nov 2026: the Roborock library's reconnect loop swallowed the cancel at the end of
    asyncio.run, so a restart from the Modules page stopped Themi and never started it
    again. What's left over now gets a moment, is named in the log, and is left behind."""
    from themi import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "LEFTOVER_GRACE_SECONDS", 0.05)
    tidy_finished: list[bool] = []

    async def stubborn() -> None:
        while True:
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                continue  # as roborock's _run_reconnect_loop does

    async def tidy() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            tidy_finished.append(True)
            raise

    left: list[asyncio.Task[None]] = []

    async def main() -> None:
        left.append(asyncio.create_task(stubborn(), name="roborock"))
        left.append(asyncio.create_task(tidy(), name="tidy"))
        await asyncio.sleep(0)

    started = time.monotonic()
    stuck = runtime_module.run_to_end(main())
    assert time.monotonic() - started < 5
    assert stuck == ["roborock"]
    assert tidy_finished == [True]


def test_run_to_end_passes_on_what_main_raises() -> None:
    from themi import runtime as runtime_module

    async def main() -> None:
        raise PortInUse("Port 8080 is already in use")

    with pytest.raises(PortInUse):
        runtime_module.run_to_end(main())
