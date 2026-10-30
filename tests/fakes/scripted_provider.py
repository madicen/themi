"""A fake AI provider that plays back scripted responses and records requests.

    provider = ScriptedProvider()
    provider.fail(2, status=503)                       # next two chat calls fail
    provider.queue_tool_call("remember_fact", {"fact": "vet is on Tuesdays"})
    provider.queue_text("Got it.")
    ...
    assert "vet" in provider.requests[-1].messages[-1].text

Each operation (chat, structured, transcribe, embed) has its own queue. Running out
of scripted responses fails the test loudly rather than inventing an answer, except
`embed`, which falls back to `embed_with` (a text-to-vector function, such as
`tests.fakes.embedder.TopicEmbedder`) when one is set.
`take(seconds)` makes the next chat call take that long on the frozen clock.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from itertools import count
from typing import Any, Literal

from themi import clock
from themi.ai.errors import CapabilityError, RefusalError, RetryableError, error_for_status
from themi.ai.provider import DEFAULT_MAX_TOKENS, Capabilities
from themi.ai.types import (
    CallKind,
    ChatResponse,
    Embeddings,
    Message,
    StopReason,
    StructuredResponse,
    TextBlock,
    ToolCall,
    ToolSpec,
    Transcription,
    Usage,
)

Operation = Literal["chat", "structured", "transcribe", "embed"]


@dataclass
class RecordedRequest:
    op: Operation
    kind: CallKind
    system: str = ""
    messages: tuple[Message, ...] = ()
    tools: tuple[ToolSpec, ...] = ()
    prompt: str = ""
    schema: dict[str, Any] | None = None
    audio: bytes = b""
    mime_type: str = ""
    max_tokens: int = DEFAULT_MAX_TOKENS
    texts: tuple[str, ...] = ()

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]


@dataclass
class ScriptedProvider:
    name: str = "scripted"
    model: str = "scripted-1"
    capabilities: Capabilities = field(default_factory=lambda: Capabilities(audio=True))
    requests: list[RecordedRequest] = field(default_factory=list)
    embed_with: Callable[[str], Sequence[float]] | None = None

    def __post_init__(self) -> None:
        self._queues: dict[Operation, deque[object]] = {
            "chat": deque(),
            "structured": deque(),
            "transcribe": deque(),
            "embed": deque(),
        }
        self._ids = count(1)
        self._takes: deque[float] = deque()

    # ----- scripting ----------------------------------------------------------

    def queue_text(self, text: str) -> ScriptedProvider:
        self._push("chat", self._chat(Message("assistant", (TextBlock(text),)), StopReason.END))
        return self

    def queue_tool_call(
        self, name: str, arguments: dict[str, Any], *, text: str = "", call_id: str | None = None
    ) -> ScriptedProvider:
        return self.queue_tool_calls([(name, arguments, call_id)], text=text)

    def queue_tool_calls(
        self, calls: Sequence[tuple[str, dict[str, Any], str | None]], *, text: str = ""
    ) -> ScriptedProvider:
        blocks: list[TextBlock | ToolCall] = [TextBlock(text)] if text else []
        for name, arguments, call_id in calls:
            blocks.append(ToolCall(call_id or f"call_{next(self._ids)}", name, arguments))
        self._push("chat", self._chat(Message("assistant", tuple(blocks)), StopReason.TOOL_USE))
        return self

    def queue_structured(self, data: dict[str, Any]) -> ScriptedProvider:
        self._push("structured", StructuredResponse(data, self.name, self.model, Usage(10, 10)))
        return self

    def queue_transcription(self, text: str) -> ScriptedProvider:
        self._push("transcribe", Transcription(text, self.name, self.model))
        return self

    def queue_error(self, error: Exception, op: Operation = "chat") -> ScriptedProvider:
        self._push(op, error)
        return self

    def fail(
        self,
        times: int,
        *,
        status: int = 503,
        retry_after: float | None = None,
        op: Operation = "chat",
    ) -> ScriptedProvider:
        """Queue `times` failures with an HTTP-style status (retryable or not)."""
        for _ in range(times):
            error = error_for_status(status, f"scripted {status}", retry_after)
            if isinstance(error, RetryableError):
                error.retry_after = retry_after
            self._push(op, error)
        return self

    def queue_refusal(
        self, category: str | None = None, op: Operation = "chat"
    ) -> ScriptedProvider:
        return self.queue_error(RefusalError(category=category), op)

    def take(self, seconds: float) -> ScriptedProvider:
        """The next chat or embed call moves the frozen clock on by `seconds`, a second at a time,
        letting other tasks run in between, before it answers."""
        self._takes.append(seconds)
        return self

    def pending(self, op: Operation = "chat") -> int:
        return len(self._queues[op])

    @property
    def last_request(self) -> RecordedRequest:
        assert self.requests, "ScriptedProvider has not been called yet"
        return self.requests[-1]

    # ----- Provider interface -------------------------------------------------

    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.INTERACTIVE,
    ) -> ChatResponse:
        self.requests.append(
            RecordedRequest(
                "chat",
                kind,
                system=system,
                messages=tuple(messages),
                tools=tuple(tools),
                max_tokens=max_tokens,
            )
        )
        if self._takes:
            await _pass(self._takes.popleft())
        result = self._pop("chat")
        assert isinstance(result, ChatResponse)
        return result

    async def structured(
        self,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.BACKGROUND,
    ) -> StructuredResponse:
        self.requests.append(
            RecordedRequest(
                "structured",
                kind,
                system=system,
                prompt=prompt,
                schema=schema,
                max_tokens=max_tokens,
            )
        )
        result = self._pop("structured")
        assert isinstance(result, StructuredResponse)
        return result

    async def transcribe(
        self, audio: bytes, mime_type: str, *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Transcription:
        self.requests.append(RecordedRequest("transcribe", kind, audio=audio, mime_type=mime_type))
        result = self._pop("transcribe")
        assert isinstance(result, Transcription)
        return result

    async def embed(
        self, texts: Sequence[str], *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Embeddings:
        self.requests.append(RecordedRequest("embed", kind, texts=tuple(texts)))
        if self._takes:
            await _pass(self._takes.popleft())
        if self._queues["embed"]:
            result = self._pop("embed")
            assert isinstance(result, Embeddings)
            return result
        if self.embed_with is None:
            raise CapabilityError(f"{self.name} has no embeddings scripted")
        vectors = tuple(tuple(self.embed_with(t)) for t in texts)
        return Embeddings(vectors, self.name, self.model)

    # ----- internals ----------------------------------------------------------

    def _chat(self, message: Message, stop: StopReason) -> ChatResponse:
        return ChatResponse(message, stop, self.name, self.model, Usage(10, 10))

    def _push(self, op: Operation, item: object) -> None:
        self._queues[op].append(item)

    def _pop(self, op: Operation) -> object:
        queue = self._queues[op]
        if not queue:
            raise AssertionError(f"ScriptedProvider: no scripted {op} response left")
        item = queue.popleft()
        if isinstance(item, Exception):
            raise item
        return item


async def _pass(seconds: float) -> None:
    whole, rest = divmod(seconds, 1)
    for step in [1.0] * int(whole) + ([rest] if rest else []):
        for _ in range(20):  # let a waiting task notice, and finish what it starts
            await asyncio.sleep(0)
        clock.advance(timedelta(seconds=step))  # the answer comes the moment the time is up
