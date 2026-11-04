"""D5a, D5b: `make dev` started as the runner starts it, with the fakes, for tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.fakes.telegram_api import FakeTelegram
from themi.cli import build_runtime
from themi.runtime import Runtime
from tools.dev import runner
from tools.dev.fakes import FAKES_FILE, DevFakes


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
        linked = await fakes.bind(runtime.app, runner.site_urls(settings)[0], runtime.scheduler)
        runs.append(DevRun(fakes, runtime, linked))
        return runs[-1]

    yield start
    finish()
