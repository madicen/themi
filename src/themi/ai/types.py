"""Provider-neutral request and response types.

Adapters translate these to and from each SDK. Nothing outside `themi.ai`
should need to know which provider answered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

Role = Literal["user", "assistant"]


class CallKind(StrEnum):
    """Someone is waiting on an interactive call; background work can wait longer."""

    INTERACTIVE = "interactive"
    BACKGROUND = "background"


class StopReason(StrEnum):
    END = "end"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


Block = TextBlock | ToolCall | ToolResult


@dataclass(frozen=True)
class Message:
    role: Role
    content: tuple[Block, ...]
    # The provider's own form of an assistant turn (e.g. Claude's content blocks,
    # including thinking blocks that must be sent back unchanged). Adapters reuse
    # it when the same provider sees the conversation again, and ignore it otherwise.
    raw: Any = field(default=None, compare=False, repr=False)
    raw_provider: str | None = field(default=None, compare=False)

    @classmethod
    def user(cls, text: str) -> Message:
        return cls("user", (TextBlock(text),))

    @classmethod
    def tool_results(cls, *results: ToolResult) -> Message:
        """All results for one assistant turn go back together in a single message."""
        return cls("user", tuple(results))

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    @property
    def tool_calls(self) -> tuple[ToolCall, ...]:
        return tuple(b for b in self.content if isinstance(b, ToolCall))


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may call. `input_schema` is JSON Schema (object type)."""

    name: str
    description: str
    input_schema: dict[str, Any]
    side_effect: bool = False


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ChatResponse:
    message: Message
    stop_reason: StopReason
    provider: str
    model: str
    usage: Usage = Usage()

    @property
    def text(self) -> str:
        return self.message.text

    @property
    def tool_calls(self) -> tuple[ToolCall, ...]:
        return self.message.tool_calls


@dataclass(frozen=True)
class StructuredResponse:
    data: dict[str, Any]
    provider: str
    model: str
    usage: Usage = Usage()


@dataclass(frozen=True)
class Transcription:
    text: str
    provider: str
    model: str


@dataclass(frozen=True)
class Embeddings:
    """One vector per text, in order. Vectors from different models can't be compared."""

    vectors: tuple[tuple[float, ...], ...]
    provider: str
    model: str
