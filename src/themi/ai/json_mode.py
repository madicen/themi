"""JSON action mode, for models that can't call tools reliably.

Instead of passing tools, the conversation and the tool catalogue go into
one prompt, and the model answers with JSON:

    {"reply": "Noted, the oil's on the list.", "actions": [
        {"tool": "update_pantry", "arguments": {"item": "olive oil", "status": "out"}}]}

Each action is validated against the same JSON Schema the tool uses. If the
output is invalid, the model gets one more try with the error included;
after that the reply is returned with no actions at all. Because actions
come back as ordinary `ToolCall`s, the agent loop and the trust tiers treat
them exactly like native tool calls.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from itertools import count
from typing import Any

import jsonschema

from themi.ai.errors import MalformedOutputError
from themi.ai.types import (
    ChatResponse,
    Message,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)

# (system, prompt, schema) -> parsed JSON object
StructuredCall = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]

_ids = count(1)


def response_schema(tools: Sequence[ToolSpec]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "reply": {"type": "string", "description": "What to say to the person."},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string", "enum": [t.name for t in tools]},
                        "arguments": {"type": "object"},
                    },
                    "required": ["tool", "arguments"],
                },
            },
        },
        "required": ["reply", "actions"],
    }


def render_instructions(system: str, tools: Sequence[ToolSpec]) -> str:
    catalogue = "\n".join(
        f"- {t.name}: {t.description}\n  arguments schema: {json.dumps(t.input_schema)}"
        for t in tools
    )
    return (
        f"{system}\n\n"
        "You can take actions by listing them in your answer. Available actions:\n"
        f"{catalogue}\n\n"
        'Answer with only a JSON object: {"reply": <text for the person>, '
        '"actions": [{"tool": <name>, "arguments": {...}}]}. Use an empty actions '
        "list when nothing needs doing."
    )


def render_transcript(messages: Sequence[Message]) -> str:
    lines = []
    for message in messages:
        for block in message.content:
            if isinstance(block, TextBlock) and block.text:
                speaker = "Person" if message.role == "user" else "You"
                lines.append(f"{speaker}: {block.text}")
            elif isinstance(block, ToolCall):
                lines.append(f"You took action {block.name} {json.dumps(block.arguments)}")
            elif isinstance(block, ToolResult):
                outcome = "failed" if block.is_error else "result"
                lines.append(f"Action {outcome}: {block.content}")
    return "Conversation so far:\n" + "\n".join(lines) + "\n\nYour JSON answer:"


def validate(data: dict[str, Any], tools: Sequence[ToolSpec]) -> list[ToolCall]:
    """Raise MalformedOutputError unless every action names a tool and fits its schema."""
    try:
        jsonschema.validate(data, response_schema(tools))
    except jsonschema.ValidationError as exc:
        raise MalformedOutputError(f"answer doesn't match the format: {exc.message}") from exc
    by_name = {t.name: t for t in tools}
    calls = []
    for action in data["actions"]:
        spec = by_name[action["tool"]]
        try:
            jsonschema.validate(action["arguments"], spec.input_schema)
        except jsonschema.ValidationError as exc:
            raise MalformedOutputError(
                f"arguments for {spec.name} are invalid: {exc.message}"
            ) from exc
        calls.append(ToolCall(f"json_{next(_ids)}", spec.name, dict(action["arguments"])))
    return calls


async def chat(
    structured: StructuredCall,
    system: str,
    messages: Sequence[Message],
    tools: Sequence[ToolSpec],
    *,
    provider: str,
    model: str,
) -> ChatResponse:
    instructions = render_instructions(system, tools)
    prompt = render_transcript(messages)
    schema = response_schema(tools)
    reply = ""
    for attempt in range(2):
        try:
            data = await structured(instructions, prompt, schema)
            if isinstance(data.get("reply"), str):
                reply = data["reply"]
            calls = validate(data, tools)
        except MalformedOutputError as exc:
            if attempt == 0:
                prompt = (
                    f"{prompt}\n\nYour previous answer was rejected: {exc}. "
                    "Answer again with valid JSON."
                )
                continue
            break
        blocks: tuple[TextBlock | ToolCall, ...] = (
            *((TextBlock(reply),) if reply else ()),
            *calls,
        )
        stop = StopReason.TOOL_USE if calls else StopReason.END
        return ChatResponse(Message("assistant", blocks), stop, provider, model, Usage())
    # Two invalid answers: say what the model wanted to say, but do nothing.
    blocks_only_text = (TextBlock(reply),) if reply else ()
    return ChatResponse(
        Message("assistant", blocks_only_text), StopReason.END, provider, model, Usage()
    )
