"""The Claude adapter against a local fake of the Messages API, over real HTTP."""

import pytest

from tests.fakes.http_ai import (
    FakeAIServer,
    anthropic_error,
    anthropic_message,
    anthropic_text,
    anthropic_tool_use,
)
from themi.ai import (
    CallKind,
    CapabilityError,
    Message,
    PermanentError,
    RefusalError,
    RetryableError,
    StopReason,
    ToolResult,
    ToolSpec,
    call_with_retry,
)
from themi.ai.adapters.anthropic import SERVER_FALLBACK_BETA, AnthropicProvider
from themi.storage.secrets import Secret

KEY = "sk-ant-test-key-for-the-fake-server"
REMEMBER = ToolSpec(
    "remember_fact",
    "Store a household fact",
    {
        "type": "object",
        "properties": {"fact": {"type": "string"}},
        "required": ["fact"],
        "additionalProperties": False,
    },
)


def provider(fake_ai: FakeAIServer, **kwargs) -> AnthropicProvider:
    return AnthropicProvider(Secret(KEY), base_url=fake_ai.url, timeout=2.0, **kwargs)


async def test_plain_reply_and_request_shape(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(anthropic_text("Hi Erin"))
    response = await provider(fake_ai).chat("Be warm.", [Message.user("hello")])

    assert response.text == "Hi Erin"
    assert response.stop_reason is StopReason.END
    assert (response.provider, response.model) == ("anthropic", "claude-opus-5-5")
    assert (response.usage.input_tokens, response.usage.output_tokens) == (12, 7)

    (request,) = fake_ai.requests
    assert request.path == "/v1/messages"
    body = request.json
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == "Be warm."
    assert body["output_config"] == {"effort": "medium"}
    assert body["fallbacks"] == "default"
    assert SERVER_FALLBACK_BETA in request.headers["anthropic-beta"]
    # SDK 2.x sends the key as a bearer token; older versions used x-api-key.
    sent_key = request.headers.get("x-api-key") or request.headers["authorization"].removeprefix(
        "Bearer "
    )
    assert sent_key == KEY
    for banned in ("temperature", "top_p", "top_k", "tool_choice", "thinking"):
        assert banned not in body


async def test_tool_round_trip_replays_thinking_blocks_unchanged(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(anthropic_tool_use("remember_fact", {"fact": "vet on Tuesdays"}))
    fake_ai.queue(anthropic_text("I'll remember that."))
    claude = provider(fake_ai)

    first = await claude.chat("sys", [Message.user("the vet is tuesdays")], [REMEMBER])
    assert first.stop_reason is StopReason.TOOL_USE
    (call,) = first.tool_calls
    assert (call.id, call.name, call.arguments) == (
        "toolu_1",
        "remember_fact",
        {"fact": "vet on Tuesdays"},
    )

    history = [
        Message.user("the vet is tuesdays"),
        first.message,
        Message.tool_results(ToolResult(call.id, "stored")),
    ]
    second = await claude.chat("sys", history, [REMEMBER])
    assert second.text == "I'll remember that."

    first_body, second_body = (r.json for r in fake_ai.requests)
    assert first_body["tools"][0]["strict"] is True
    assistant = second_body["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == {
        "type": "thinking",
        "thinking": "",
        "signature": "sig-abc123",
    }
    assert assistant["content"][1]["type"] == "tool_use"
    assert second_body["messages"][2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "stored", "is_error": False}
    ]


async def test_turns_from_other_providers_are_rebuilt(fake_ai: FakeAIServer) -> None:
    from themi.ai import TextBlock, ToolCall

    foreign = Message(
        "assistant",
        (TextBlock("checking"), ToolCall("call_9", "remember_fact", {"fact": "x"})),
        raw={"gemini": "content"},
        raw_provider="gemini",
    )
    fake_ai.queue(anthropic_text("ok"))
    await provider(fake_ai).chat(
        "sys", [Message.user("hi"), foreign, Message.tool_results(ToolResult("call_9", "done"))]
    )
    assistant = fake_ai.requests[0].json["messages"][1]["content"]
    assert assistant == [
        {"type": "text", "text": "checking"},
        {"type": "tool_use", "id": "call_9", "name": "remember_fact", "input": {"fact": "x"}},
    ]


async def test_structured_output(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(anthropic_text('{"category": "noise", "summary": "a sale"}'))
    schema = {
        "type": "object",
        "properties": {"category": {"type": "string"}, "summary": {"type": "string"}},
        "required": ["category", "summary"],
        "additionalProperties": False,
    }
    result = await provider(fake_ai).structured("Classify.", "Big sale!", schema)
    assert result.data == {"category": "noise", "summary": "a sale"}
    assert fake_ai.requests[0].json["output_config"]["format"] == {
        "type": "json_schema",
        "schema": schema,
    }


async def test_structured_output_that_isnt_json(fake_ai: FakeAIServer) -> None:
    from themi.ai.errors import MalformedOutputError

    fake_ai.queue(anthropic_text("sure! here you go"))
    with pytest.raises(MalformedOutputError):
        await provider(fake_ai).structured("s", "p", {"type": "object"})


@pytest.mark.parametrize(
    ("status", "error_type", "expected", "retry_after"),
    [
        (529, "overloaded_error", RetryableError, "3"),
        (429, "rate_limit_error", RetryableError, "11"),
        (500, "api_error", RetryableError, None),
        (503, "api_error", RetryableError, None),
        (400, "invalid_request_error", PermanentError, None),
        (401, "authentication_error", PermanentError, None),
        (403, "permission_error", PermanentError, None),
        (404, "not_found_error", PermanentError, None),
    ],
)
async def test_errors_map_to_our_types_with_one_request_each(
    fake_ai: FakeAIServer, status: int, error_type: str, expected: type, retry_after: str | None
) -> None:
    headers = {"retry-after": retry_after} if retry_after else {}
    fake_ai.queue(anthropic_error(error_type, "nope"), status=status, headers=headers)
    with pytest.raises(expected) as info:
        await provider(fake_ai).chat("sys", [Message.user("hi")])
    assert info.value.status == status
    assert "nope" in str(info.value)
    assert KEY not in str(info.value)
    if retry_after:
        assert info.value.retry_after == float(retry_after)
    assert len(fake_ai.requests) == 1  # the SDK's own retries are off


async def test_timeout_is_retryable(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(anthropic_text("too late"), delay=1.5)
    claude = AnthropicProvider(Secret(KEY), base_url=fake_ai.url, timeout=0.3)
    with pytest.raises(RetryableError, match="timed out"):
        await claude.chat("sys", [Message.user("hi")])
    assert len(fake_ai.requests) == 1


async def test_refusal_raises_with_category(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(
        anthropic_message(
            [],
            "refusal",
            stop_details={"type": "refusal", "category": "cyber", "explanation": "no"},
        )
    )
    with pytest.raises(RefusalError) as info:
        await provider(fake_ai).chat("sys", [Message.user("hi")])
    assert info.value.category == "cyber"


async def test_models_without_server_fallback_omit_it(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(anthropic_text("hi", model="claude-haiku-5-5"))
    await AnthropicProvider(
        Secret(KEY), "claude-haiku-5-5", base_url=fake_ai.url, effort="low"
    ).chat("sys", [Message.user("hi")])
    (request,) = fake_ai.requests
    assert "fallbacks" not in request.json
    assert SERVER_FALLBACK_BETA not in request.headers.get("anthropic-beta", "")
    assert request.json["output_config"] == {"effort": "low"}


async def test_transcription_is_not_supported(fake_ai: FakeAIServer) -> None:
    with pytest.raises(CapabilityError):
        await provider(fake_ai).transcribe(b"ogg", "audio/ogg")
    assert fake_ai.requests == []


async def test_retry_policy_and_adapter_together(fake_ai: FakeAIServer) -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    fake_ai.queue(anthropic_error("overloaded_error"), status=529, headers={"retry-after": "2"})
    fake_ai.queue(anthropic_text("back"))
    claude = provider(fake_ai)
    response = await call_with_retry(
        lambda: claude.chat("sys", [Message.user("hi")]), CallKind.INTERACTIVE, sleep=sleep
    )
    assert response.text == "back"
    assert len(fake_ai.requests) == 2 and waits == [2.0]
