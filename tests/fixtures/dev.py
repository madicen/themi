"""D5a-D5c: `make dev` started as the runner starts it, with the fakes, and its control
panel served by a simulator, for tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fakes.telegram_api import FakeTelegram
from themi.cli import build_runtime
from themi.runtime import Runtime
from tools.dev import runner
from tools.dev.controls import ControlPanel
from tools.dev.fakes import FAKES_FILE, DevFakes
from tools.dev.simulator import Simulator


@dataclass
class DevRun:
    fakes: DevFakes
    runtime: Runtime
    linked: list[str]

    def count(self, sql: str) -> int:
        return int(self.runtime.app.db.scalar(sql) or 0)


Boot = Callable[[], Awaitable[DevRun]]


@pytest.fixture
async def boot(
    tmp_path: Path, fake_telegram: FakeTelegram, frozen_clock: object
) -> AsyncIterator[Boot]:
    """Start dev on `tmp_path` as the runner does, up to Themi running; each call is a run,
    and the last one is stopped (and saved) before the next starts."""
    runs: list[DevRun] = []

    def finish() -> None:
        if runs and runs[-1].fakes.app is not None:
            last = runs[-1]
            last.fakes.save()
            last.fakes.stop()
            last.runtime.app.db.close()
            last.fakes.app = None

    async def start() -> DevRun:
        finish()
        settings = runner.dev_settings(
            tmp_path, fake_telegram.base_url.removesuffix("/bot"), {"THEMI_DEV_HTTP_PORT": "8081"}
        )
        runner.seed(settings, "")
        fakes = DevFakes(tmp_path / FAKES_FILE)
        fakes.start(runner.site_urls(settings))
        runtime = build_runtime(
            settings, connectors=fakes.connectors(runner.family_timezone(settings))
        )
        linked = await fakes.bind(
            runtime.app, runner.site_urls(settings)[0], runtime.scheduler, runtime.web
        )
        runs.append(DevRun(fakes, runtime, linked))
        return runs[-1]

    yield start
    finish()


@dataclass
class Panel:
    run: DevRun
    sim: Simulator
    client: httpx.AsyncClient

    async def act(self, section: str, action: str, **values: Any) -> httpx.Response:
        return await self.client.post(
            "/control/act", json={"section": section, "action": action, "values": values}
        )

    async def ok(self, section: str, action: str, **values: Any) -> str:
        response = await self.act(section, action, **values)
        assert response.status_code == 200, response.text
        return response.json()["happened"]

    def rows(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        return self.run.runtime.app.db.query(sql, params)

    def device_state(self, name: str) -> str:
        """The state Themi last read for that device ("" if it never has)."""
        rows = self.rows(
            "SELECT s.state FROM device_states s JOIN devices d ON d.id = s.device_id "
            "WHERE d.name = ?",
            name,
        )
        return rows[0]["state"] if rows else ""


@pytest.fixture
async def panel(boot: Boot) -> AsyncIterator[Panel]:
    run = await boot()
    sim = Simulator()
    sim.start()
    sim.controls = ControlPanel(run.fakes)
    # Async, so Themi's loop (this test's) is free to make each change while we wait.
    async with httpx.AsyncClient(base_url=sim.url, timeout=30) as client:
        yield Panel(run, sim, client)
    sim.stop()
