"""Any OpenAI-compatible chat-completions server: Ollama, LM Studio, vLLM,
llama.cpp server, OpenRouter, and OpenAI itself.

Local models vary a lot, so capabilities are set per configuration rather
than assumed. When a model can't call tools reliably, mark `tools=False` and
the router switches to JSON action mode (prompt 06) instead of passing tools.

- SDK retries are off (`max_retries=0`); `themi.ai.retry` owns retries.
- Structured output uses `response_format: json_schema` by default. Servers
  that only understand `json_object` can use `structured_mode="json_object"`,
  which also puts the schema in the prompt.
- Tool-call arguments that aren't valid JSON raise `MalformedOutputError`
  rather than guessing.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal

import openai

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

OLLAMA_URL = "http://localhost:11434/v1"
LM_STUDIO_URL = "http://localhost:1234/v1"

StructuredMode = Literal["json_schema", "json_object"]

_STOP_REASONS = {
    "stop": StopReason.END,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
}


class OpenAICompatProvider:
    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: Secret | None = None,
        name: str = "openai_compat",
        capabilities: Capabilities | None = None,
        structured_mode: StructuredMode = "json_schema",
        transcription_model: str | None = None,
        timeout: float = 60.0,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.capabilities = capabilities or Capabilities(tools=True, structured=True, audio=False)
        self.structured_mode = structured_mode
        self.transcription_model = transcription_model or model
        # Local servers ignore the key but the SDK insists on one.
        key = api_key.reveal() if api_key else "not-needed"
        self._client = client or openai.AsyncOpenAI(
            api_key=key, base_url=base_url, timeout=timeout, max_retries=0
        )

    @classmethod
    def ollama(
        cls, model: str, *, base_url: str = OLLAMA_URL, **kwargs: Any
    ) -> OpenAICompatProvider:
        return cls(model, base_url=base_url, name="ollama", **kwargs)

    @classmethod
    def lm_studio(
        cls, model: str, *, base_url: str = LM_STUDIO_URL, **kwargs: Any
    ) -> OpenAICompatProvider:
        return cls(model, base_url=base_url, name="lm_studio", **kwargs)

    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.INTERACTIVE,
    ) -> ChatResponse:
        if tools and not self.capabilities.tools:
            raise CapabilityError(f"{self.name}:{self.model} is configured without tool support")
        params: dict[str, Any] = {
            "model": self.model,
            "messages": _messages(system, messages),
            "max_tokens": max_tokens,
        }
        if tools:
            params["tools"] = [_tool(t) for t in tools]
        completion = await self._call(self._client.chat.completions.create(**params))
        choice = completion.choices[0]
        if choice.finish_reason == "content_filter":
            raise RefusalError(f"{self.name} filtered this response", category="content_filter")
        blocks: list[TextBlock | ToolCall] = []
        if choice.message.content:
            blocks.append(TextBlock(choice.message.content))
        for call in choice.message.tool_calls or []:
            blocks.append(ToolCall(call.id, call.function.name, _arguments(call, self.name)))
        stop = _STOP_REASONS.get(choice.finish_reason or "", StopReason.END)
        if any(isinstance(b, ToolCall) for b in blocks):
            stop = StopReason.TOOL_USE
        return ChatResponse(
            Message("assistant", tuple(blocks)), stop, self.name, self.model, _usage(completion)
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
        if not self.capabilities.structured:
            raise CapabilityError(f"{self.name}:{self.model} is configured without JSON output")
        if self.structured_mode == "json_schema":
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            }
        else:
            response_format = {"type": "json_object"}
            prompt = f"{prompt}\n\nReply with only a JSON object matching this schema:\n" + (
                json.dumps(schema)
            )
        completion = await self._call(
            self._client.chat.completions.create(
                model=self.model,
                messages=_messages(system, [Message.user(prompt)]),
                max_tokens=max_tokens,
                response_format=response_format,  # type: ignore[arg-type]
            )
        )
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            raise MalformedOutputError(f"{self.name} structured output was cut off")
        return StructuredResponse(
            parse_json_object(choice.message.content or "", self.name),
            self.name,
            self.model,
            _usage(completion),
        )

    async def transcribe(
        self, audio: bytes, mime_type: str, *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Transcription:
        if not self.capabilities.audio:
            raise CapabilityError(f"{self.name}:{self.model} is configured without audio input")
        extension = mime_type.split("/")[-1].split(";")[0] or "ogg"
        result = await self._call(
            self._client.audio.transcriptions.create(
                model=self.transcription_model, file=(f"voice.{extension}", audio, mime_type)
            )
        )
        return Transcription(result.text.strip(), self.name, self.transcription_model)

    async def _call(self, request: Any) -> Any:
        try:
            return await request
        except openai.APITimeoutError as exc:
            raise RetryableError(f"{self.name} request timed out") from exc
        except openai.APIConnectionError as exc:
            raise RetryableError(f"couldn't connect to {self.name}") from exc
        except openai.APIStatusError as exc:
            raise error_for_status(
                exc.status_code,
                f"{self.name} returned {exc.status_code}: {exc.message}",
                parse_retry_after(exc.response.headers.get("retry-after")),
            ) from exc


def _tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.input_schema,
        },
    }


def _messages(system: str, messages: Sequence[Message]) -> list[Any]:
    # list[Any]: these dicts match the SDK's message param TypedDicts at runtime.
    converted: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
    for message in messages:
        if message.role == "assistant":
            calls = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in message.tool_calls
            ]
            entry: dict[str, Any] = {"role": "assistant", "content": message.text or None}
            if calls:
                entry["tool_calls"] = calls
            converted.append(entry)
            continue
        text = "".join(b.text for b in message.content if isinstance(b, TextBlock))
        if text:
            converted.append({"role": "user", "content": text})
        for block in message.content:
            if isinstance(block, ToolResult):
                content = f"Error: {block.content}" if block.is_error else block.content
                converted.append(
                    {"role": "tool", "tool_call_id": block.tool_call_id, "content": content}
                )
    return converted


def _arguments(call: Any, provider: str) -> dict[str, Any]:
    raw = call.function.arguments or "{}"
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedOutputError(
            f"{provider} returned tool arguments that aren't JSON for {call.function.name}"
        ) from exc
    if not isinstance(arguments, dict):
        raise MalformedOutputError(f"{provider} returned non-object tool arguments")
    return arguments


def _usage(completion: Any) -> Usage:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return Usage()
    return Usage(usage.prompt_tokens or 0, usage.completion_tokens or 0)
