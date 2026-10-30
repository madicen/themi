"""Spacing real model calls so free-tier per-minute limits hold.

Each model gets its own limiter, shared by every provider the router builds
for it, so the limit holds however many calls one case makes. This runs only
in the opt-in evals, which is why it can really wait.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from themi.ai.adapters import AdapterConfig, build_provider
from themi.ai.provider import Provider


class MinuteLimiter:
    """At most `rpm` calls in any rolling 60 seconds."""

    def __init__(
        self,
        rpm: int,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.rpm = rpm
        self.now = now
        self.sleep = sleep
        # No lock: each eval test has its own event loop, and calls run one at a time.
        self.calls: deque[float] = deque()
        self.waited = 0.0  # seconds spent waiting, kept out of P5's model timings

    async def wait(self) -> None:
        while True:
            moment = self.now()
            while self.calls and moment - self.calls[0] >= 60:
                self.calls.popleft()
            if len(self.calls) < self.rpm:
                self.calls.append(moment)
                return
            pause = 60 - (moment - self.calls[0]) + 0.1
            await self.sleep(pause)
            self.waited += pause


class PacedProvider:
    """A real provider whose calls wait their turn."""

    def __init__(self, inner: Provider, limiter: MinuteLimiter) -> None:
        self.inner = inner
        self.limiter = limiter

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def model(self) -> str:
        return self.inner.model

    @property
    def capabilities(self) -> Any:
        return self.inner.capabilities

    async def chat(self, system: str, messages: Sequence[Any], tools: Sequence[Any] = (), **kw):
        await self.limiter.wait()
        return await self.inner.chat(system, messages, tools, **kw)

    async def structured(self, system: str, prompt: str, schema: dict[str, Any], **kw):
        await self.limiter.wait()
        return await self.inner.structured(system, prompt, schema, **kw)

    async def transcribe(self, *args: Any, **kw: Any):
        await self.limiter.wait()
        return await self.inner.transcribe(*args, **kw)


class PacedFactory:
    """The router's provider factory for evals: real adapters, one limiter per model."""

    def __init__(self, rpm: int) -> None:
        self.rpm = rpm
        self.limiters: dict[str, MinuteLimiter] = {}

    @property
    def waited(self) -> float:
        """Seconds every model has spent waiting for its minute so far."""
        return sum(limiter.waited for limiter in self.limiters.values())

    def __call__(self, config: AdapterConfig) -> Provider:
        inner = build_provider(config)
        if self.rpm <= 0:
            return inner
        limiter = self.limiters.setdefault(config.resolved_model, MinuteLimiter(self.rpm))
        return PacedProvider(inner, limiter)  # type: ignore[return-value]
