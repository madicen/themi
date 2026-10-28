"""The only way the rest of Themi reaches a model.

    client = router.client_for(member_id, AITask.CONVERSATION)
    response = await client.chat(system, messages, tools)

For each call the router walks the member's chain for that task:

1. Skip a backend whose circuit breaker is open.
2. Build the provider from the member's own settings. Keys never cross
   members: a shared task runs on the backend of the member who owns it, so
   callers pass that member's id.
3. Try it under the retry policy. A backend that can't do the job (no audio,
   no key, bad config, malformed output, a refusal) is skipped to the next.
4. A model without tool support gets the request in JSON action mode.

If every backend fails, interactive calls raise `AllProvidersFailed` (or the
`RefusalError` itself, if every backend declined), and background calls
raise `Deferred` so the scheduler re-queues the work instead of dropping it.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeVar

from themi import clock
from themi.ai import json_mode
from themi.ai.adapters import AdapterConfig, build_provider
from themi.ai.breaker import BreakerBoard, BreakerState
from themi.ai.errors import (
    AIError,
    CapabilityError,
    MalformedOutputError,
    PermanentError,
    RefusalError,
    RetriesExhausted,
    RetryableError,
)
from themi.ai.provider import DEFAULT_MAX_TOKENS, Provider
from themi.ai.retry import DEFAULT_POLICY, OnRetry, RetryPolicy, Sleep, call_with_retry
from themi.ai.settings import AISettingsStore, AITask, ResolvedEntry
from themi.ai.types import (
    CallKind,
    ChatResponse,
    Message,
    StructuredResponse,
    ToolSpec,
    Transcription,
)
from themi.localtime import to_utc_iso

T = TypeVar("T")
ProviderFactory = Callable[[AdapterConfig], Provider]
Operation = Callable[[Provider], Awaitable[T]]

log = logging.getLogger(__name__)

CONNECTION_TEST_PROMPT = "Reply with the single word OK."
CALLS_KEPT = timedelta(days=7)  # ai_calls history (bug #29)
# The reply (P2a's `replies` row) the calls being made now are for, if any.
current_reply: ContextVar[int | None] = ContextVar("current_reply", default=None)


class CircuitOpenError(AIError):
    """This backend's breaker is open; it's skipped without a request."""


class _ChainFailed(AIError):
    def __init__(self, message: str, errors: Sequence[tuple[str, Exception]]) -> None:
        details = "; ".join(f"{label}: {type(e).__name__}: {e}" for label, e in errors)
        super().__init__(f"{message} ({details})" if errors else message)
        self.errors = list(errors)

    @property
    def needs_setup(self) -> bool:
        """True when nothing was even tried for a transient reason: settings need fixing."""
        return not self.errors or all(
            isinstance(e, PermanentError | CapabilityError) for _, e in self.errors
        )


class AllProvidersFailed(_ChainFailed):
    """Every backend in an interactive chain failed. Tell the person plainly."""


class Deferred(_ChainFailed):
    """Every backend in a background chain failed. Re-queue the work for later."""

    @property
    def retry_after(self) -> float | None:
        hints = [
            e.last_error.retry_after
            for _, e in self.errors
            if isinstance(e, RetriesExhausted) and e.last_error.retry_after is not None
        ]
        return max(hints) if hints else None


_SKIP_TO_NEXT = (
    RetriesExhausted,
    PermanentError,
    CapabilityError,
    MalformedOutputError,
    RefusalError,
    CircuitOpenError,
)


@dataclass(frozen=True)
class ConnectionResult:
    ok: bool
    label: str
    provider: str
    model: str
    detail: str


class AIRouter:
    def __init__(
        self,
        settings: AISettingsStore,
        *,
        policy: RetryPolicy = DEFAULT_POLICY,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
        breakers: BreakerBoard | None = None,
        factory: ProviderFactory | None = None,
    ) -> None:
        self.settings = settings
        self.policy = policy
        self.breakers = breakers or BreakerBoard()
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._factory = factory or build_provider

    def client_for(self, member_id: int, task: AITask) -> TaskClient:
        return TaskClient(self, member_id, AITask(task))

    def _chain(self, member_id: int, task: AITask) -> list[ResolvedEntry]:
        entries = self.settings.resolve(member_id, task)
        if not entries:
            self.settings.ensure_defaults(member_id)
            entries = self.settings.resolve(member_id, task)
        return entries

    async def run(
        self,
        member_id: int,
        task: AITask,
        kind: CallKind,
        operation: Operation[T],
        on_retry: OnRetry | None = None,
    ) -> T:
        errors: list[tuple[str, Exception]] = []
        call = _CallRecord(clock.now())

        async def noted(attempt: int, error: RetryableError, wait: float) -> None:
            call.retries += 1
            call.waited += wait
            call.last_status = error.status
            if on_retry is not None:
                result = on_retry(attempt, error, wait)
                if inspect.isawaitable(result):
                    await result

        for entry in self._chain(member_id, task):
            if not self.breakers.allow(member_id, entry.backend_id):
                errors.append((entry.label, CircuitOpenError("temporarily skipped")))
                continue
            call.backend = entry.label
            try:
                provider = self._factory(entry.config)
                result = await self._attempt(member_id, entry, provider, operation, kind, noted)
                self._record(member_id, task, kind, call, ok=True)
                return result
            except _SKIP_TO_NEXT as exc:
                if not isinstance(exc, RetriesExhausted | CircuitOpenError):
                    self.breakers.release_probe(member_id, entry.backend_id)
                log.warning(
                    "AI %s for member %s: %s failed (%s), trying the next backend",
                    task.value,
                    member_id,
                    entry.label,
                    type(exc).__name__,
                )
                errors.append((entry.label, exc))
        last = errors[-1][1] if errors else None
        if isinstance(last, RetriesExhausted):
            call.last_status = last.last_error.status or call.last_status
        elif isinstance(last, AIError) and getattr(last, "status", None):
            call.last_status = getattr(last, "status", None)
        self._record(member_id, task, kind, call, ok=False)
        if errors and all(isinstance(e, RefusalError) for _, e in errors):
            raise errors[-1][1]
        failure = Deferred if kind is CallKind.BACKGROUND else AllProvidersFailed
        raise failure(f"no AI backend could handle {task.value}", errors)

    def _record(
        self, member_id: int, task: AITask, kind: CallKind, call: _CallRecord, *, ok: bool
    ) -> None:
        """Keep a week of calls: how long, how long waiting, how it ended (bug #29)."""
        db = self.settings.db
        now = clock.now()
        try:
            db.execute(
                "INSERT INTO ai_calls (member_id, task, kind, backend, started_at, seconds, "
                "waited, retries, last_status, ok, reply_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    member_id, task.value, kind.value, call.backend, to_utc_iso(call.started),
                    round((now - call.started).total_seconds(), 2), round(call.waited, 2),
                    call.retries, call.last_status, int(ok), current_reply.get(),
                ),
            )  # fmt: skip
            db.execute("DELETE FROM ai_calls WHERE started_at < ?", (to_utc_iso(now - CALLS_KEPT),))
        except sqlite3.Error:  # never lose an answer over a note about it
            log.warning("Couldn't record an AI call", exc_info=True)

    async def _attempt(
        self,
        member_id: int,
        entry: ResolvedEntry,
        provider: Provider,
        operation: Operation[T],
        kind: CallKind,
        on_retry: OnRetry | None,
    ) -> T:
        async def once() -> T:
            if self.breakers.state(member_id, entry.backend_id) is BreakerState.OPEN:
                raise CircuitOpenError("breaker opened during retries")
            try:
                result = await operation(provider)
            except Exception as exc:
                if isinstance(exc, RetryableError | TimeoutError | ConnectionError):
                    self.breakers.record_failure(member_id, entry.backend_id)
                raise
            self.breakers.record_success(member_id, entry.backend_id)
            return result

        return await call_with_retry(
            once, kind, policy=self.policy, sleep=self._sleep, rng=self._rng, on_retry=on_retry
        )

    async def test_connection(
        self, member_id: int, task: AITask, position: int = 0
    ) -> ConnectionResult:
        """Try one backend of a member's chain (no fallback), for the website's test button."""
        entries = self._chain(member_id, AITask(task))
        if not 0 <= position < len(entries):
            return ConnectionResult(False, "", "", "", "there's no backend at that position")
        entry = entries[position]
        model = entry.config.resolved_model
        try:
            provider = self._factory(entry.config)
            if task is AITask.TRANSCRIPTION and not provider.capabilities.audio:
                raise CapabilityError(f"{provider.name} can't transcribe voice notes")
            response = await call_with_retry(
                lambda: provider.chat(
                    CONNECTION_TEST_PROMPT, [Message.user("ping")], max_tokens=2000
                ),
                CallKind.INTERACTIVE,
                policy=self.policy,
                sleep=self._sleep,
                rng=self._rng,
            )
        except AIError as exc:
            return ConnectionResult(False, entry.label, entry.config.kind, model, str(exc))
        return ConnectionResult(
            True, entry.label, response.provider, response.model, "Connected and answering."
        )


@dataclass
class _CallRecord:
    started: datetime
    backend: str = ""
    retries: int = 0
    waited: float = 0.0
    last_status: int | None = None


class TaskClient:
    """A member's view of one AI task. Mirrors the Provider operations."""

    def __init__(self, router: AIRouter, member_id: int, task: AITask) -> None:
        self._router = router
        self.member_id = member_id
        self.task = task

    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.INTERACTIVE,
        on_retry: OnRetry | None = None,
    ) -> ChatResponse:
        async def operation(provider: Provider) -> ChatResponse:
            if tools and not provider.capabilities.tools:
                if not provider.capabilities.structured:
                    raise CapabilityError(f"{provider.name} supports neither tools nor JSON")

                async def structured(
                    system_: str, prompt: str, schema: dict[str, Any]
                ) -> dict[str, Any]:
                    result = await provider.structured(
                        system_, prompt, schema, max_tokens=max_tokens, kind=kind
                    )
                    return result.data

                return await json_mode.chat(
                    structured,
                    system,
                    messages,
                    tools,
                    provider=provider.name,
                    model=provider.model,
                )
            return await provider.chat(system, messages, tools, max_tokens=max_tokens, kind=kind)

        return await self._router.run(self.member_id, self.task, kind, operation, on_retry)

    async def structured(
        self,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.BACKGROUND,
        on_retry: OnRetry | None = None,
    ) -> StructuredResponse:
        async def operation(provider: Provider) -> StructuredResponse:
            if not provider.capabilities.structured:
                raise CapabilityError(f"{provider.name} can't return structured output")
            return await provider.structured(
                system, prompt, schema, max_tokens=max_tokens, kind=kind
            )

        return await self._router.run(self.member_id, self.task, kind, operation, on_retry)

    async def transcribe(
        self,
        audio: bytes,
        mime_type: str,
        *,
        kind: CallKind = CallKind.INTERACTIVE,
        on_retry: OnRetry | None = None,
    ) -> Transcription:
        async def operation(provider: Provider) -> Transcription:
            if not provider.capabilities.audio:
                raise CapabilityError(f"{provider.name} can't transcribe audio")
            return await provider.transcribe(audio, mime_type, kind=kind)

        return await self._router.run(self.member_id, self.task, kind, operation, on_retry)
