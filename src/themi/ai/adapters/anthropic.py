"""Claude, through the official Anthropic SDK.

- SDK retries are off (`max_retries=0`); `themi.ai.retry` owns retries.
- Thinking is left at the model default (adaptive on Claude Opus 5.5). Depth
  is set with `output_config.effort`, which defaults to `medium` on that model,
  so it is always sent explicitly.
- No sampling parameters (temperature/top_p/top_k) and no forced tool choice:
  current models reject both.
- On models that support it, refusals are retried server-side on Anthropic's
  recommended fallback model (`fallbacks: "default"`). A refusal that still
  comes back raises `RefusalError`.
- An assistant turn keeps the SDK's content blocks in `Message.raw`. Thinking
  blocks must go back unchanged in the next request of a tool loop, so a turn
  this adapter produced is always replayed from `raw`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import anthropic

from themi.ai.adapters._common import parse_json_object
from themi.ai.errors import (
    CapabilityError,
    MalformedOutputError,
    RefusalError,
    RetryableError,
    error_for_status,
    parse_retry_after,
)
from themi.ai.provider import DEFAULT_MAX_TOKENS, Capabilities
from themi.ai.types import (
    CallKind,
    ChatResponse,
    Message,
    StopReason,
    StructuredResponse,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolSpec,
    Transcription,
    Usage,
)
from themi.storage.secrets import Secret

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept `fallbacks: "default"` on the Claude API.
SERVER_FALLBACK_MODELS = frozenset(
    {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
)

_STOP_REASONS = {
    "end_turn": StopReason.END,
    "stop_sequence": StopReason.END,
    "pause_turn": StopReason.END,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
}


class AnthropicProvider:
    name = "anthropic"
    capabilities = Capabilities(tools=True, structured=True, audio=False)

    def __init__(
        self,
        api_key: Secret,
        model: str = DEFAULT_MODEL,
        *,
        base_url: str | None = None,
        timeout: float = 60.0,
        effort: str = DEFAULT_EFFORT,
        server_fallback: bool | None = None,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.server_fallback = (
            model in SERVER_FALLBACK_MODELS if server_fallback is None else server_fallback
        )
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key.reveal(), base_url=base_url, timeout=timeout, max_retries=0
        )

    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.INTERACTIVE,
    ) -> ChatResponse:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": self._messages(messages),
            "output_config": {"effort": self.effort},
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = [_tool(t) for t in tools]
        response = await self._create(params)
        message = Message(
            "assistant",
            tuple(_blocks(response.content)),
            raw=list(response.content),
            raw_provider=self.name,
        )
        return ChatResponse(
            message,
            _STOP_REASONS.get(response.stop_reason or "", StopReason.END),
            self.name,
            response.model,
            _usage(response),
        )

    async def structured(
        self,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.BACKGROUND,
    ) -> StructuredResponse:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        }
        if system:
            params["system"] = system
        response = await self._create(params)
        if response.stop_reason == "max_tokens":
            raise MalformedOutputError("anthropic structured output was cut off at max_tokens")
        text = "".join(b.text for b in response.content if b.type == "text")
        return StructuredResponse(
            parse_json_object(text, self.name), self.name, response.model, _usage(response)
        )

    async def transcribe(
        self, audio: bytes, mime_type: str, *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Transcription:
        raise CapabilityError("Claude doesn't accept audio input; route transcription elsewhere")

    # ----- internals ----------------------------------------------------------

    async def _create(self, params: dict[str, Any]) -> Any:
        if self.server_fallback:
            params = {**params, "betas": [SERVER_FALLBACK_BETA], "fallbacks": "default"}
        try:
            response = await self._client.beta.messages.create(**params)
        except anthropic.APITimeoutError as exc:
            raise RetryableError("anthropic request timed out") from exc
        except anthropic.APIConnectionError as exc:
            raise RetryableError("couldn't connect to anthropic") from exc
        except anthropic.APIStatusError as exc:
            raise error_for_status(
                exc.status_code,
                f"anthropic returned {exc.status_code}: {_error_message(exc)}",
                parse_retry_after(exc.response.headers.get("retry-after")),
            ) from exc
        if response.stop_reason == "refusal":
            details = response.stop_details
            raise RefusalError(
                getattr(details, "explanation", None) or "Claude declined this request",
                category=getattr(details, "category", None),
            )
        return response

    def _messages(self, messages: Sequence[Message]) -> list[dict[str, Any]]:
        converted = []
        for message in messages:
            if message.role == "assistant" and message.raw_provider == self.name and message.raw:
                content: Any = message.raw
            else:
                content = [_block_param(block) for block in message.content]
            converted.append({"role": message.role, "content": content})
        return converted


def _tool(spec: ToolSpec) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.input_schema,
    }
    # Strict mode guarantees schema-valid arguments, but needs a closed schema.
    if spec.input_schema.get("additionalProperties") is False:
        tool["strict"] = True
    return tool


def _block_param(block: TextBlock | ToolCall | ToolResult) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolCall):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.arguments}
    return {
        "type": "tool_result",
        "tool_use_id": block.tool_call_id,
        "content": block.content,
        "is_error": block.is_error,
    }


def _blocks(content: Sequence[Any]) -> list[TextBlock | ToolCall]:
    blocks: list[TextBlock | ToolCall] = []
    for block in content:
        if block.type == "text":
            blocks.append(TextBlock(block.text))
        elif block.type == "tool_use":
            blocks.append(ToolCall(block.id, block.name, dict(block.input or {})))
        # thinking, fallback and other blocks stay in Message.raw only
    return blocks


def _usage(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage()
    return Usage(usage.input_tokens or 0, usage.output_tokens or 0)


def _error_message(exc: anthropic.APIStatusError) -> str:
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return exc.message
