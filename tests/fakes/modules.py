"""CR1: the core services alone, for installing one module at a time in a unit test.

    services = bare_services(family.store)
    ctx = ModuleContext(services, scheduler=Scheduler(family.db))
    ctx.load(BreaksModule())

Nothing here sends: the outbox's sender refuses, so a test that needs messages uses the
scenario harness instead.
"""

from __future__ import annotations

from typing import Any

from themi.accounts import AccountStore
from themi.ai.router import AIRouter
from themi.ai.settings import AISettingsStore
from themi.autonomy import Autonomy, ExecutorRegistry
from themi.channels.calibration import PdaCalibrator
from themi.channels.outbox import Outbox
from themi.channels.pda import PdaShield
from themi.core.services import Services
from themi.core.tools import ToolRegistry


class RefusingSender:
    async def send_text(self, *args: Any, **kwargs: Any) -> int:
        raise AssertionError("a module sent a message while being installed")

    async def edit_text(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("a module edited a message while being installed")


def bare_services(store: AccountStore) -> Services:
    ai_settings = AISettingsStore(store.db, store.cipher)
    return Services(
        store=store,
        ai_settings=ai_settings,
        router=AIRouter(ai_settings),
        outbox=Outbox(store, RefusingSender(), PdaShield(None)),  # type: ignore[arg-type]
        calibrator=PdaCalibrator(store),
        tools=ToolRegistry(),
        autonomy=Autonomy(store, ExecutorRegistry()),
    )
