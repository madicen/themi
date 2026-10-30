"""The Gemini adapter against a local fake of generateContent, over real HTTP."""

import base64

import pytest

from tests.fakes.http_ai import (
    FakeAIServer,
    gemini_error,
    gemini_function_call,
    gemini_response,
    gemini_text,
)
from themi.ai import (
    Message,
    PermanentError,
    RefusalError,
    RetryableError,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from themi.ai.adapters.gemini import GeminiProvider
from themi.ai.errors import MalformedOutputError
from themi.storage.secrets import Secret

KEY = "AIzaFakeKeyForTheLocalFakeServer0000000"
UPDATE_PANTRY = ToolSpec(
    "update_pantry",
    "Mark a pantry item's status",
    {
        "type": "object",
        "properties": {"item": {"type": "string"}, "status": {"type": "string"}},
        "required": ["item", "status"],
    },
)


def field(obj: dict, camel: str):
    """The SDK sends some fields in snake_case; Google's JSON parser accepts both."""
    snake = "".join(f"_{c.lower()}" if c.isupper() else c for c in camel)
    return obj[camel] if camel in obj else obj[snake]


def provider(fake_ai: FakeAIServer, **kwargs) -> GeminiProvider:
    return GeminiProvider(Secret(KEY), base_url=fake_ai.url, timeout=2.0, **kwargs)


async def test_plain_reply_and_request_shape(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(gemini_text("Hi Erin"))
    response = await provider(fake_ai).chat("Be warm.", [Message.user("hello")])

    assert response.text == "Hi Erin"
    assert response.stop_reason is StopReason.END
    assert (response.provider, response.model) == ("gemini", "gemini-3.5-flash-lite")
    assert response.usage.output_tokens == 7

    (request,) = fake_ai.requests
    assert request.path.endswith("/models/gemini-3.5-flash-lite:generateContent")
    assert request.headers["x-goog-api-key"] == KEY
    body = request.json
    assert body["systemInstruction"]["parts"][0]["text"] == "Be warm."
    assert body["contents"] == [{"role": "user", "parts": [{"text": "hello"}]}]
    assert body["generationConfig"]["maxOutputTokens"] == 16000


async def test_function_call_round_trip_keeps_thought_signature(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(gemini_function_call("update_pantry", {"item": "olive oil", "status": "out"}))
    fake_ai.queue(gemini_text("Marked it."))
    gemini = provider(fake_ai)

    first = await gemini.chat("sys", [Message.user("used the last olive oil")], [UPDATE_PANTRY])
    assert first.stop_reason is StopReason.TOOL_USE
    (call,) = first.tool_calls
    assert (call.id, call.name, call.arguments) == (
        "fc_1",
        "update_pantry",
        {"item": "olive oil", "status": "out"},
    )

    history = [
        Message.user("used the last olive oil"),
        first.message,
        Message.tool_results(ToolResult(call.id, "updated")),
    ]
    assert (await gemini.chat("sys", history, [UPDATE_PANTRY])).text == "Marked it."

    first_body, second_body = (r.json for r in fake_ai.requests)
    declaration = first_body["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "update_pantry"
    assert field(declaration, "parametersJsonSchema") == UPDATE_PANTRY.input_schema
    model_turn = second_body["contents"][1]
    assert model_turn["role"] == "model"
    assert model_turn["parts"][0]["thoughtSignature"] == "c2lnLTE="
    response_part = second_body["contents"][2]["parts"][0]["functionResponse"]
    assert response_part == {
        "id": "fc_1",
        "name": "update_pantry",
        "response": {"result": "updated"},
    }


async def test_calls_without_ids_get_generated_ones(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(
        gemini_function_call("update_pantry", {"item": "rice", "status": "low"}, call_id=None)
    )
    response = await provider(fake_ai).chat("sys", [Message.user("rice low")], [UPDATE_PANTRY])
    assert response.tool_calls[0].id.startswith("gemini_")


async def test_foreign_turns_and_error_results_are_rebuilt(fake_ai: FakeAIServer) -> None:
    foreign = Message(
        "assistant",
        (TextBlock("let me check"), ToolCall("toolu_7", "update_pantry", {"item": "eggs"})),
        raw=["claude blocks"],
        raw_provider="anthropic",
    )
    fake_ai.queue(gemini_text("ok"))
    await provider(fake_ai).chat(
        "sys",
        [
            Message.user("eggs?"),
            foreign,
            Message.tool_results(ToolResult("toolu_7", "no such item", is_error=True)),
        ],
    )
    contents = fake_ai.requests[0].json["contents"]
    assert contents[1]["parts"][1]["functionCall"] == {
        "id": "toolu_7",
        "name": "update_pantry",
        "args": {"item": "eggs"},
    }
    assert contents[2]["parts"][0]["functionResponse"]["response"] == {"error": "no such item"}


async def test_structured_output(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(gemini_text('{"category": "receipt"}'))
    schema = {"type": "object", "properties": {"category": {"type": "string"}}}
    result = await provider(fake_ai).structured("Classify.", "Your Safeway receipt", schema)
    assert result.data == {"category": "receipt"}
    config = fake_ai.requests[0].json["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == schema


async def test_transcription_sends_inline_audio(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(gemini_text("used the last olive oil\n"))
    result = await provider(fake_ai, model="gemini-3.5-flash-lite").transcribe(
        b"OggS-fake-audio", "audio/ogg"
    )
    assert result.text == "used the last olive oil"
    parts = fake_ai.requests[0].json["contents"][0]["parts"]
    inline = field(parts[0], "inlineData")
    assert field(inline, "mimeType") == "audio/ogg"
    assert inline["data"] == base64.b64encode(b"OggS-fake-audio").decode()
    assert "gemini-3.5-flash-lite" in fake_ai.requests[0].path


@pytest.mark.parametrize(
    ("code", "status", "expected", "retry_delay", "retry_after"),
    [
        (429, "RESOURCE_EXHAUSTED", RetryableError, "37s", 37.0),
        (429, "RESOURCE_EXHAUSTED", RetryableError, None, None),
        (500, "INTERNAL", RetryableError, None, None),
        (503, "UNAVAILABLE", RetryableError, None, None),
        (400, "INVALID_ARGUMENT", PermanentError, None, None),
        (403, "PERMISSION_DENIED", PermanentError, None, None),
        (404, "NOT_FOUND", PermanentError, None, None),
    ],
)
async def test_errors_map_to_our_types(
    fake_ai: FakeAIServer,
    code: int,
    status: str,
    expected: type,
    retry_delay: str | None,
    retry_after: float | None,
) -> None:
    fake_ai.queue(gemini_error(code, status, "quota or similar", retry_delay), status=code)
    with pytest.raises(expected) as info:
        await provider(fake_ai).chat("sys", [Message.user("hi")])
    assert info.value.status == code
    assert KEY not in str(info.value)
    if expected is RetryableError:
        assert info.value.retry_after == retry_after
    assert len(fake_ai.requests) == 1  # the SDK's own retries are off


async def test_retry_after_header_wins(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(gemini_error(503, "UNAVAILABLE"), status=503, headers={"retry-after": "4"})
    with pytest.raises(RetryableError) as info:
        await provider(fake_ai).chat("sys", [Message.user("hi")])
    assert info.value.retry_after == 4.0


async def test_timeout_is_retryable(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(gemini_text("too late"), delay=1.5)
    gemini = GeminiProvider(Secret(KEY), base_url=fake_ai.url, timeout=0.3)
    with pytest.raises(RetryableError):
        await gemini.chat("sys", [Message.user("hi")])


@pytest.mark.parametrize("finish", ["SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"])
async def test_safety_finish_reasons_are_refusals(fake_ai: FakeAIServer, finish: str) -> None:
    fake_ai.queue(gemini_response([], finish))
    with pytest.raises(RefusalError) as info:
        await provider(fake_ai).chat("sys", [Message.user("hi")])
    assert info.value.category == finish.lower()


async def test_blocked_prompt_is_a_refusal(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(gemini_response([], prompt_feedback={"blockReason": "SAFETY"}))
    with pytest.raises(RefusalError) as info:
        await provider(fake_ai).chat("sys", [Message.user("hi")])
    assert info.value.category == "SAFETY"


async def test_max_tokens_stop(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(gemini_text("partial", finish_reason="MAX_TOKENS"))
    response = await provider(fake_ai).chat("sys", [Message.user("hi")])
    assert response.stop_reason is StopReason.MAX_TOKENS


# ----- embeddings (P7b) --------------------------------------------------------------


async def test_embeddings_one_vector_per_text(fake_ai: FakeAIServer) -> None:
    fake_ai.queue({"embeddings": [{"values": [0.6, 0.8]}, {"values": [1.0, 0.0]}]})
    gemini = provider(fake_ai, model="gemini-embedding-2")
    got = await gemini.embed(["lie down for a bit", "oat milk"])
    assert got.vectors == ((0.6, 0.8), (1.0, 0.0))
    assert (got.provider, got.model) == ("gemini", "gemini-embedding-2")
    (request,) = fake_ai.requests
    assert "gemini-embedding-2" in request.path and "mbed" in request.path
    body = str(request.json)
    assert "lie down for a bit" in body and "oat milk" in body
    assert "SEMANTIC_SIMILARITY" in body and "768" in body


async def test_embeddings_errors_map_like_chat(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(gemini_error(429, "RESOURCE_EXHAUSTED", "quota"), status=429)
    with pytest.raises(RetryableError):
        await provider(fake_ai, model="gemini-embedding-2").embed(["hi"])


async def test_too_few_embeddings_is_malformed(fake_ai: FakeAIServer) -> None:
    fake_ai.queue({"embeddings": [{"values": [1.0]}]})
    with pytest.raises(MalformedOutputError):
        await provider(fake_ai, model="gemini-embedding-2").embed(["one", "two"])
