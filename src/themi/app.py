"""Assemble Themi from its parts.

One function builds the whole object graph, so the CLI, the scenario
harness and `themi run` (prompt 10) all run the same wiring.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from themi.accounts import AccountStore
from themi.ai.retry import Sleep
from themi.ai.router import AIRouter, ProviderFactory
from themi.ai.settings import AISettingsStore
from themi.channels.calibration import PdaCalibrator
from themi.channels.outbox import Outbox
from themi.channels.pda import AIRewriter, PdaShield
from themi.channels.telegram import TelegramChannel
from themi.core.agent import Agent
from themi.core.services import Services
from themi.core.starter_tools import STARTER_TOOLS
from themi.core.tools import ToolRegistry
from themi.storage.db import Database
from themi.storage.secrets import Cipher

ChannelFactory = Callable[[AccountStore], TelegramChannel]


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
    )
    agent = Agent(services)
    channel.handler = agent
    return App(db, store, ai_settings, router, channel, outbox, services, agent)
