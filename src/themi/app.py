"""Assemble Themi from its parts.

One function builds the whole object graph, so the CLI, the scenario
harness and `themi run` (prompt 10) all run the same wiring.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta

from themi.accounts import AccountStore
from themi.ai.retry import Sleep
from themi.ai.router import AIRouter, ProviderFactory
from themi.ai.settings import AISettingsStore
from themi.autonomy import Autonomy, ExecutorRegistry
from themi.channels.calibration import PdaCalibrator
from themi.channels.outbox import Outbox
from themi.channels.pda import AIRewriter, PdaShield
from themi.channels.telegram import TelegramChannel
from themi.core.agent import Agent
from themi.core.approvals import ApprovalsUI
from themi.core.commands import Commands
from themi.core.memory import Memory
from themi.core.rules import Rulebook
from themi.core.services import Services
from themi.core.starter_tools import STARTER_TOOLS
from themi.core.tools import ToolRegistry
from themi.storage.db import Database
from themi.storage.secrets import Cipher

ChannelFactory = Callable[[AccountStore], TelegramChannel]


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    every: timedelta
    run: Callable[[], Awaitable[object]]


@dataclass
class App:
    db: Database
    store: AccountStore
    ai_settings: AISettingsStore
    router: AIRouter
    channel: TelegramChannel
    outbox: Outbox
    services: Services
    agent: Agent
    approvals: ApprovalsUI
    rulebook: Rulebook
    periodic: list[PeriodicTask] = field(default_factory=list)


def build_app(
    db: Database,
    cipher: Cipher,
    make_channel: ChannelFactory,
    *,
    provider_factory: ProviderFactory | None = None,
    sleep: Sleep = asyncio.sleep,
) -> App:
    store = AccountStore(db, cipher)
    ai_settings = AISettingsStore(db, cipher)
    router = AIRouter(ai_settings, factory=provider_factory, sleep=sleep)
    channel = make_channel(store)
    outbox = Outbox(store, channel, PdaShield(AIRewriter(router)))
    services = Services(
        store=store,
        ai_settings=ai_settings,
        router=router,
        outbox=outbox,
        calibrator=PdaCalibrator(store),
        tools=ToolRegistry(list(STARTER_TOOLS)),
        autonomy=Autonomy(store, ExecutorRegistry()),
    )
    approvals = ApprovalsUI(services.autonomy, outbox)
    approvals.install(services)
    rulebook = Rulebook(services.autonomy, outbox)
    rulebook.install(services)
    services.memory = Memory(db, rulebook)
    Commands(services).install()
    agent = Agent(services)
    channel.handler = agent
    periodic = [
        PeriodicTask("outbox.flush", timedelta(seconds=30), outbox.flush),
        PeriodicTask("approvals.resurface", timedelta(minutes=5), approvals.resurface),
        PeriodicTask("approvals.expire", timedelta(hours=1), approvals.expire),
        PeriodicTask("rules.expire_drafts", timedelta(hours=1), rulebook.expire_drafts),
    ]
    return App(
        db,
        store,
        ai_settings,
        router,
        channel,
        outbox,
        services,
        agent,
        approvals,
        rulebook,
        periodic,
    )
