from typing import Any

from themi.ai import Message, StopReason, ToolCall, ToolResult, ToolSpec
from themi.ai.json_mode import chat, render_transcript

UPDATE_PANTRY = ToolSpec(
    "update_pantry",
    "Mark a pantry item",
    {
        "type": "object",
        "properties": {
            "item": {"type": "string"},
            "status": {"type": "string", "enum": ["plenty", "low", "out"]},
        },
        "required": ["item", "status"],
        "additionalProperties": False,
    },
)


class Answers:
    """A structured-call stand-in that returns queued JSON and records prompts."""

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.systems: list[str] = []

    async def __call__(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.systems.append(system)
        self.prompts.append(prompt)
        return self.answers.pop(0)


async def run(answers: Answers, messages=None):
    return await chat(
        answers,
        "You help a household.",
        messages or [Message.user("used the last olive oil")],
        [UPDATE_PANTRY],
        provider="ollama",
        model="qwen-test",
    )


async def test_valid_actions_become_tool_calls() -> None:
    answers = Answers(
        {
            "reply": "Noted.",
            "actions": [
                {"tool": "update_pantry", "arguments": {"item": "olive oil", "status": "out"}}
            ],
        }
    )
    response = await run(answers)
    assert response.stop_reason is StopReason.TOOL_USE
    assert response.text == "Noted."
    (call,) = response.tool_calls
    assert (call.name, call.arguments) == ("update_pantry", {"item": "olive oil", "status": "out"})
    assert "update_pantry" in answers.systems[0]
    assert '"enum": ["plenty", "low", "out"]' in answers.systems[0]


async def test_no_actions_is_a_plain_reply() -> None:
    response = await run(Answers({"reply": "Hi there!", "actions": []}))
    assert response.stop_reason is StopReason.END
    assert response.text == "Hi there!" and response.tool_calls == ()


async def test_invalid_output_gets_one_retry_with_the_error() -> None:
    answers = Answers(
        {"reply": "Noted.", "actions": [{"tool": "update_pantry", "arguments": {"item": "oil"}}]},
        {
            "reply": "Noted.",
            "actions": [{"tool": "update_pantry", "arguments": {"item": "oil", "status": "out"}}],
        },
    )
    response = await run(answers)
    assert len(answers.prompts) == 2
    assert "rejected" in answers.prompts[1] and "status" in answers.prompts[1]
    assert response.tool_calls[0].arguments == {"item": "oil", "status": "out"}


async def test_two_invalid_answers_mean_reply_only_no_actions() -> None:
    answers = Answers(
        {"reply": "On it.", "actions": [{"tool": "delete_everything", "arguments": {}}]},
        {"reply": "On it!", "actions": [{"tool": "update_pantry", "arguments": {"item": 3}}]},
    )
    response = await run(answers)
    assert response.stop_reason is StopReason.END
    assert response.tool_calls == ()
    assert response.text == "On it!"


async def test_missing_reply_field_counts_as_invalid() -> None:
    response = await run(Answers({"actions": []}, {"actions": []}))
    assert response.tool_calls == () and response.text == ""


def test_transcript_includes_actions_and_results() -> None:
    messages = [
        Message.user("used the oil"),
        Message(
            "assistant", (ToolCall("json_1", "update_pantry", {"item": "oil", "status": "out"}),)
        ),
        Message.tool_results(ToolResult("json_1", "updated"), ToolResult("json_2", "nope", True)),
    ]
    text = render_transcript(messages)
    assert "Person: used the oil" in text
    assert 'You took action update_pantry {"item": "oil", "status": "out"}' in text
    assert "Action result: updated" in text and "Action failed: nope" in text
