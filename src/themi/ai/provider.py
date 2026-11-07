"""The interface every AI backend implements.

Four operations, all async:
- `chat`: one model turn, optionally with tools. The caller runs the tool loop.
- `structured`: an answer that matches a JSON Schema.
- `transcribe`: voice note to text.
- `embed`: texts to vectors (P7b), or `CapabilityError` where there's no such API.
- `image`: a picture from a prompt (BD4a), or `CapabilityError` where there's no such API.

Adapters make exactly one request per call and never retry on their own;
`themi.ai.retry` owns retries so attempts aren't multiplied.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from themi.ai.types import (
    CallKind,
    ChatResponse,
    Embeddings,
    ImageResult,
    Message,
    StructuredResponse,
    ToolSpec,
    Transcription,
)

DEFAULT_MAX_TOKENS = 16_000
IMAGE_SIZE = "1024x1024"  # square, the cheapest size each image API offers


@dataclass(frozen=True)
class Capabilities:
    tools: bool = True
    structured: bool = True
    audio: bool = False


@runtime_checkable
class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def capabilities(self) -> Capabilities: ...

    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.INTERACTIVE,
    ) -> ChatResponse: ...

    async def structured(
        self,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.BACKGROUND,
    ) -> StructuredResponse: ...

    async def transcribe(
        self, audio: bytes, mime_type: str, *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Transcription: ...

    async def embed(
        self, texts: Sequence[str], *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Embeddings: ...

    async def image(
        self, prompt: str, size: str = IMAGE_SIZE, *, kind: CallKind = CallKind.BACKGROUND
    ) -> ImageResult: ...
