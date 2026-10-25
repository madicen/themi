import pytest

from tests.fakes.scripted_provider import ScriptedProvider
from themi.ai import (
    CallKind,
    Message,
    PermanentError,
    Provider,
    RefusalError,
    RetryableError,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolSpec,
)

REMEMBER = ToolSpec(
    "remember_fact",
    "Store a fact",
    {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]},
)


def test_satisfies_the_provider_protocol() -> None:
    assert isinstance(ScriptedProvider(), Provider)


async def test_plays_back_chat_responses_in_order_and_records_requests() -> None:
    provider = ScriptedProvider()
    provider.queue_tool_call("remember_fact", {"fact": "vet on Tuesdays"}, text="Noting that.")
    provider.queue_text("Got it.")

    first = await provider.chat("sys", [Message.user("vet is tuesdays")], [REMEMBER])
    assert first.stop_reason is StopReason.TOOL_USE
    assert first.text == "Noting that."
    (call,) = first.tool_calls
    assert (call.name, call.arguments) == ("remember_fact", {"fact": "vet on Tuesdays"})

    history = [
        Message.user("vet is tuesdays"),
        first.message,
        Message.tool_results(ToolResult(call.id, "stored")),
    ]
    second = await provider.chat("sys", history, [REMEMBER], kind=CallKind.BACKGROUND)
    assert second.stop_reason is StopReason.END and second.text == "Got it."

    assert [r.op for r in provider.requests] == ["chat", "chat"]
    assert provider.requests[0].tool_names == ["remember_fact"]
    assert provider.last_request.kind is CallKind.BACKGROUND
    assert len(provider.last_request.messages) == 3


async def test_parallel_tool_calls_get_distinct_ids() -> None:
    provider = ScriptedProvider().queue_tool_calls(
        [("a", {}, None), ("b", {"x": 1}, None), ("c", {}, "fixed")]
    )
    response = await provider.chat("sys", [Message.user("go")])
    ids = [c.id for c in response.tool_calls]
    assert len(set(ids)) == 3 and ids[2] == "fixed"


async def test_operations_have_separate_queues() -> None:
    provider = ScriptedProvider()
    provider.queue_structured({"category": "noise"})
    provider.queue_transcription("used the last olive oil")
    provider.queue_text("chat reply")

    assert (await provider.transcribe(b"ogg", "audio/ogg")).text == "used the last olive oil"
    assert (await provider.structured("sys", "classify", {"type": "object"})).data == {
        "category": "noise"
    }
    assert (await provider.chat("sys", [Message.user("hi")])).text == "chat reply"
    assert provider.requests[0].audio == b"ogg"
    assert provider.requests[1].schema == {"type": "object"}


async def test_failures_and_refusals_are_raised_in_sequence() -> None:
    provider = ScriptedProvider().fail(1, status=503, retry_after=4).fail(1, status=401)
    provider.queue_refusal("bio").queue_text("finally")
    with pytest.raises(RetryableError) as retryable:
        await provider.chat("s", [Message.user("1")])
    assert (retryable.value.status, retryable.value.retry_after) == (503, 4)
    with pytest.raises(PermanentError):
        await provider.chat("s", [Message.user("2")])
    with pytest.raises(RefusalError) as refusal:
        await provider.chat("s", [Message.user("3")])
    assert refusal.value.category == "bio"
    assert (await provider.chat("s", [Message.user("4")])).text == "finally"
    assert len(provider.requests) == 4


async def test_running_out_of_script_fails_loudly() -> None:
    provider = ScriptedProvider()
    with pytest.raises(AssertionError, match="no scripted chat response"):
        await provider.chat("s", [Message.user("hi")])
    assert provider.pending() == 0


def test_message_helpers() -> None:
    message = Message("assistant", (TextBlock("a"), ToolCall("1", "t", {}), TextBlock("b")))
    assert message.text == "ab"
    assert [c.name for c in message.tool_calls] == ["t"]
    with_raw = Message("assistant", message.content, raw={"provider": "blocks"}, raw_provider="x")
    assert with_raw == message  # raw provider data doesn't affect equality
