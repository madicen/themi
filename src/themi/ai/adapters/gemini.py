"""Gemini, through the official Google Gen AI SDK (`google-genai`).

- SDK retries are off (`HttpRetryOptions(attempts=1)`); `themi.ai.retry` owns retries.
- Automatic function calling is disabled: Themi runs the tool loop itself.
- An assistant turn keeps the SDK's `Content` in `Message.raw`, so thought
  signatures on function calls go back unchanged when the conversation
  continues on Gemini.
- Gemini reports quota exhaustion as 429 RESOURCE_EXHAUSTED, often with a
  `RetryInfo.retryDelay` in the error details; that becomes `retry_after`.
- Safety blocks (prompt or candidate) become `RefusalError`.
- Free-tier prompts may be used by Google to improve its products (per the
  Gemini API pricing page); the router and website surface that to members.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from themi.ai.adapters._common import TRANSCRIBE_PROMPT, parse_json_object, transport_exceptions
from themi.ai.errors import (
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
    Embeddings,
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

# gemini-3.8-flash allowed only 20 free requests a day; flash-lite has room for a household.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TRANSCRIPTION_MODEL = "gemini-3.5-flash-lite"
# P7b: gemini-embedding-2 told "lie down" from "oat milk" further apart than -001 did.
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_SIZE = 768  # of 3072: plenty to route on, and a quarter of the cache

REFUSAL_FINISH_REASONS = frozenset(
    {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION", "IMAGE_SAFETY"}
)
_TRANSPORT_ERRORS = transport_exceptions()


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: Secret,
        model: str = DEFAULT_MODEL,
        *,
        base_url: str | None = None,
        timeout: float = 60.0,
        audio: bool = True,
        client: genai.Client | None = None,
    ) -> None:
        self.model = model
        self.capabilities = Capabilities(tools=True, structured=True, audio=audio)
        self._ids = itertools.count(1)
        self._client = client or genai.Client(
            api_key=api_key.reveal(),
            http_options=types.HttpOptions(
                base_url=base_url,
                timeout=int(timeout * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
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
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tools=[types.Tool(function_declarations=[_declaration(t) for t in tools])]
            if tools
            else None,
        )
        response = await self._generate(self._contents(messages), config)
        candidate = _first_candidate(response)
        content = candidate.content or types.Content(role="model", parts=[])
        blocks = self._blocks(content)
        finish = _finish_name(candidate)
        if any(isinstance(b, ToolCall) for b in blocks):
            stop = StopReason.TOOL_USE
        elif finish == "MAX_TOKENS":
            stop = StopReason.MAX_TOKENS
        else:
            stop = StopReason.END
        message = Message("assistant", tuple(blocks), raw=content, raw_provider=self.name)
        return ChatResponse(message, stop, self.name, self.model, _usage(response))

    async def structured(
        self,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.BACKGROUND,
    ) -> StructuredResponse:
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        response = await self._generate(
            [types.Content(role="user", parts=[types.Part(text=prompt)])], config
        )
        if _finish_name(_first_candidate(response)) == "MAX_TOKENS":
            raise MalformedOutputError("gemini structured output was cut off at max_tokens")
        return StructuredResponse(
            parse_json_object(_text(response), self.name), self.name, self.model, _usage(response)
        )

    async def transcribe(
        self, audio: bytes, mime_type: str, *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Transcription:
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=audio, mime_type=mime_type),
                    types.Part(text=TRANSCRIBE_PROMPT),
                ],
            )
        ]
        response = await self._generate(contents, types.GenerateContentConfig())
        return Transcription(_text(response).strip(), self.name, self.model)

    async def embed(
        self, texts: Sequence[str], *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Embeddings:
        # One Content per text: gemini-embedding-2 reads a list of plain strings as the
        # parts of a single input and returns one vector.
        contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]
        config = types.EmbedContentConfig(
            task_type="SEMANTIC_SIMILARITY", output_dimensionality=EMBEDDING_SIZE
        )
        try:
            response = await self._client.aio.models.embed_content(
                model=self.model, contents=contents, config=config
            )
        except genai_errors.APIError as exc:
            raise error_for_status(
                exc.code,
                f"gemini returned {exc.code} {exc.status or ''}: {exc.message or ''}".strip(),
                _retry_after(exc),
            ) from exc
        except _TRANSPORT_ERRORS as exc:
            raise RetryableError(f"gemini transport error: {type(exc).__name__}") from exc
        vectors = tuple(tuple(e.values or ()) for e in response.embeddings or ())
        if len(vectors) != len(texts) or not all(vectors):
            raise MalformedOutputError(
                f"gemini returned {len(vectors)} embeddings for {len(texts)} texts"
            )
        return Embeddings(vectors, self.name, self.model)

    # ----- internals ----------------------------------------------------------

    async def _generate(
        self, contents: list[types.Content], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except genai_errors.APIError as exc:
            raise error_for_status(
                exc.code,
                f"gemini returned {exc.code} {exc.status or ''}: {exc.message or ''}".strip(),
                _retry_after(exc),
            ) from exc
        except _TRANSPORT_ERRORS as exc:
            raise RetryableError(f"gemini transport error: {type(exc).__name__}") from exc

        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason is not None:
            raise RefusalError(
                feedback.block_reason_message or "Gemini blocked this prompt",
                category=_enum_name(feedback.block_reason),
            )
        finish = _finish_name(_first_candidate(response))
        if finish in REFUSAL_FINISH_REASONS:
            raise RefusalError("Gemini declined this request", category=finish.lower())
        return response

    def _contents(self, messages: Sequence[Message]) -> list[types.Content]:
        # Gemini's function responses are matched by name, so remember which
        # name each tool call id had.
        names: dict[str, str] = {}
        contents = []
        for message in messages:
            for call in message.tool_calls:
                names[call.id] = call.name
            if message.role == "assistant":
                if message.raw_provider == self.name and isinstance(message.raw, types.Content):
                    contents.append(message.raw)
                else:
                    contents.append(types.Content(role="model", parts=_parts(message.content)))
            else:
                contents.append(types.Content(role="user", parts=_parts(message.content, names)))
        return contents

    def _blocks(self, content: types.Content) -> list[TextBlock | ToolCall]:
        blocks: list[TextBlock | ToolCall] = []
        for part in content.parts or []:
            if part.function_call is not None:
                call = part.function_call
                call_id = call.id or f"gemini_{next(self._ids)}"
                blocks.append(ToolCall(call_id, call.name or "", dict(call.args or {})))
            elif part.text and not part.thought:
                blocks.append(TextBlock(part.text))
        return blocks


def _declaration(spec: ToolSpec) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=spec.name, description=spec.description, parameters_json_schema=spec.input_schema
    )


def _parts(
    blocks: Sequence[TextBlock | ToolCall | ToolResult], names: dict[str, str] | None = None
) -> list[types.Part]:
    parts = []
    for block in blocks:
        if isinstance(block, TextBlock):
            parts.append(types.Part(text=block.text))
        elif isinstance(block, ToolCall):
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(
                        id=block.id, name=block.name, args=block.arguments
                    )
                )
            )
        else:
            name = (names or {}).get(block.tool_call_id, "")
            key = "error" if block.is_error else "result"
            parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        id=block.tool_call_id, name=name, response={key: block.content}
                    )
                )
            )
    return parts


def _first_candidate(response: types.GenerateContentResponse) -> types.Candidate:
    if not response.candidates:
        raise MalformedOutputError("gemini returned no candidates")
    return response.candidates[0]


def _text(response: types.GenerateContentResponse) -> str:
    content = response.candidates[0].content if response.candidates else None
    if content is None:
        return ""
    return "".join(p.text for p in content.parts or [] if p.text and not p.thought)


def _finish_name(candidate: types.Candidate) -> str:
    return _enum_name(candidate.finish_reason) or ""


def _enum_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)


def _usage(response: types.GenerateContentResponse) -> Usage:
    meta = response.usage_metadata
    if meta is None:
        return Usage()
    return Usage(meta.prompt_token_count or 0, meta.candidates_token_count or 0)


def _retry_after(exc: genai_errors.APIError) -> float | None:
    headers = getattr(exc.response, "headers", None)
    if headers is not None:
        from_header = parse_retry_after(headers.get("retry-after"))
        if from_header is not None:
            return from_header
    details = exc.details if isinstance(exc.details, dict) else {}
    error = details.get("error", details)
    for detail in error.get("details", []) if isinstance(error, dict) else []:
        delay = detail.get("retryDelay") if isinstance(detail, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                continue
    return None
