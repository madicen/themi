"""The OpenAI-compatible adapter (Ollama, LM Studio, ...) against a local fake."""

import pytest

from tests.fakes.http_ai import FakeAIServer, openai_completion, openai_error, openai_tool_call
from themi.ai import (
    Capabilities,
    CapabilityError,
    Message,
    PermanentError,
    RefusalError,
    RetryableError,
    StopReason,
    ToolResult,
    ToolSpec,
)
from themi.ai.adapters.openai_compat import OpenAICompatProvider
from themi.ai.errors import MalformedOutputError
from themi.storage.secrets import Secret

LOG_MEAL = ToolSpec(
    "log_meal",
    "Record that someone ate",
    {"type": "object", "properties": {"description": {"type": "string"}}},
)


def provider(fake_ai: FakeAIServer, **kwargs) -> OpenAICompatProvider:
    kwargs.setdefault("timeout", 2.0)
    return OpenAICompatProvider.ollama("llama-test", base_url=f"{fake_ai.url}/v1", **kwargs)


async def test_plain_reply_and_request_shape(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(openai_completion("Hi Erin"))
    response = await provider(fake_ai).chat("Be warm.", [Message.user("hello")])

    assert response.text == "Hi Erin"
    assert response.stop_reason is StopReason.END
    assert (response.provider, response.model) == ("ollama", "llama-test")

    (request,) = fake_ai.requests
    assert request.path == "/v1/chat/completions"
    assert request.json["messages"] == [
        {"role": "system", "content": "Be warm."},
        {"role": "user", "content": "hello"},
    ]
    assert request.json["max_tokens"] == 16000
    assert "tools" not in request.json


async def test_tool_round_trip(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(openai_completion(None, [openai_tool_call("log_meal", {"description": "toast"})]))
    fake_ai.queue(openai_completion("Noted."))
    local = provider(fake_ai)

    first = await local.chat("sys", [Message.user("had toast")], [LOG_MEAL])
    assert first.stop_reason is StopReason.TOOL_USE
    (call,) = first.tool_calls
    assert (call.id, call.name, call.arguments) == ("call_1", "log_meal", {"description": "toast"})

    history = [
        Message.user("had toast"),
        first.message,
        Message.tool_results(ToolResult(call.id, "logged"), ToolResult("call_x", "bad", True)),
    ]
    await local.chat("sys", history, [LOG_MEAL])
    first_body, second_body = (r.json for r in fake_ai.requests)
    assert first_body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "log_meal",
                "description": "Record that someone ate",
                "parameters": LOG_MEAL.input_schema,
            },
        }
    ]
    messages = second_body["messages"]
    assert messages[2]["role"] == "assistant"
    assert messages[2]["tool_calls"][0]["function"] == {
        "name": "log_meal",
        "arguments": '{"description": "toast"}',
    }
    assert messages[3] == {"role": "tool", "tool_call_id": "call_1", "content": "logged"}
    assert messages[4] == {"role": "tool", "tool_call_id": "call_x", "content": "Error: bad"}


async def test_tool_arguments_that_arent_json(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(openai_completion(None, [openai_tool_call("log_meal", "{description: toast")]))
    with pytest.raises(MalformedOutputError, match="log_meal"):
        await provider(fake_ai).chat("sys", [Message.user("had toast")], [LOG_MEAL])


async def test_models_without_tool_support_refuse_tools_before_calling(
    fake_ai: FakeAIServer,
) -> None:
    local = provider(fake_ai, capabilities=Capabilities(tools=False))
    with pytest.raises(CapabilityError):
        await local.chat("sys", [Message.user("hi")], [LOG_MEAL])
    assert fake_ai.requests == []


async def test_structured_output_json_schema_mode(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(openai_completion('{"options": ["toast", "soup"]}'))
    schema = {"type": "object", "properties": {"options": {"type": "array"}}}
    result = await provider(fake_ai).structured("Suggest meals.", "low energy", schema)
    assert result.data == {"options": ["toast", "soup"]}
    assert fake_ai.requests[0].json["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "result", "schema": schema, "strict": True},
    }


async def test_structured_output_json_object_mode(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(openai_completion('{"ok": true}'))
    local = provider(fake_ai, structured_mode="json_object")
    await local.structured("s", "classify", {"type": "object"})
    body = fake_ai.requests[0].json
    assert body["response_format"] == {"type": "json_object"}
    assert '{"type": "object"}' in body["messages"][-1]["content"]


async def test_structured_output_that_isnt_json(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(openai_completion("Here's what I think..."))
    with pytest.raises(MalformedOutputError):
        await provider(fake_ai).structured("s", "p", {"type": "object"})


async def test_content_filter_is_a_refusal(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(openai_completion("", finish_reason="content_filter"))
    with pytest.raises(RefusalError):
        await provider(fake_ai).chat("sys", [Message.user("hi")])


@pytest.mark.parametrize(
    ("status", "expected", "retry_after"),
    [
        (429, RetryableError, "6"),
        (500, RetryableError, None),
        (503, RetryableError, None),
        (400, PermanentError, None),
        (401, PermanentError, None),
        (404, PermanentError, None),
    ],
)
async def test_errors_map_to_our_types(
    fake_ai: FakeAIServer, status: int, expected: type, retry_after: str | None
) -> None:
    headers = {"retry-after": retry_after} if retry_after else {}
    fake_ai.queue(openai_error("model busy"), status=status, headers=headers)
    with pytest.raises(expected) as info:
        await provider(fake_ai).chat("sys", [Message.user("hi")])
    assert info.value.status == status
    if retry_after:
        assert info.value.retry_after == float(retry_after)
    assert len(fake_ai.requests) == 1  # the SDK's own retries are off


async def test_timeout_and_unreachable_server_are_retryable(fake_ai: FakeAIServer) -> None:
    fake_ai.queue(openai_completion("too late"), delay=1.5)
    with pytest.raises(RetryableError, match="timed out"):
        await provider(fake_ai, timeout=0.3).chat("sys", [Message.user("hi")])
    nowhere = OpenAICompatProvider.lm_studio("m", base_url="http://127.0.0.1:9/v1", timeout=1)
    with pytest.raises(RetryableError, match="connect"):
        await nowhere.chat("sys", [Message.user("hi")])


async def test_transcription_depends_on_configuration(fake_ai: FakeAIServer) -> None:
    with pytest.raises(CapabilityError):
        await provider(fake_ai).transcribe(b"ogg", "audio/ogg")
    fake_ai.queue({"text": " had toast "})
    whisper = OpenAICompatProvider(
        "gpt-4o-mini",
        base_url=f"{fake_ai.url}/v1",
        api_key=Secret("sk-test-openai-key-000000000000"),
        capabilities=Capabilities(audio=True),
        transcription_model="whisper-1",
    )
    result = await whisper.transcribe(b"OggS", "audio/ogg")
    assert result.text == "had toast" and result.model == "whisper-1"
    assert fake_ai.requests[0].path == "/v1/audio/transcriptions"
    assert fake_ai.requests[0].headers["authorization"] == "Bearer sk-test-openai-key-000000000000"
