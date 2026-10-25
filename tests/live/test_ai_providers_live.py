"""Smoke tests against real AI providers. Opt-in: `make test-live`.

Each test is skipped unless its credentials are in the environment:
- ANTHROPIC_API_KEY                  Claude (default model)
- GEMINI_API_KEY                     Gemini (free tier is fine)
- THEMI_LIVE_OLLAMA_MODEL            a model pulled in a local Ollama
  (THEMI_LIVE_OLLAMA_URL to override http://localhost:11434/v1)

Use test accounts, never the family's real keys.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from themi.ai import CallKind, Message, Provider, StopReason, ToolResult, ToolSpec, call_with_retry
from themi.ai.adapters import AdapterConfig, build_provider
from themi.storage.secrets import Secret

LOG_MEAL = ToolSpec(
    "log_meal",
    "Record that the user ate something.",
    {
        "type": "object",
        "properties": {"description": {"type": "string", "description": "what they ate"}},
        "required": ["description"],
        "additionalProperties": False,
    },
)


def _providers() -> list[Any]:
    params = []

    def add(name: str, env: str, make) -> None:
        value = os.environ.get(env)
        marks = [] if value else [pytest.mark.skip(reason=f"set {env} to run")]
        params.append(pytest.param(make, id=name, marks=marks))

    add(
        "claude",
        "ANTHROPIC_API_KEY",
        lambda: build_provider(
            AdapterConfig(
                "anthropic", api_key=Secret(os.environ["ANTHROPIC_API_KEY"]), effort="low"
            )
        ),
    )
    add(
        "gemini",
        "GEMINI_API_KEY",
        lambda: build_provider(
            AdapterConfig("gemini", api_key=Secret(os.environ["GEMINI_API_KEY"]))
        ),
    )
    add(
        "ollama",
        "THEMI_LIVE_OLLAMA_MODEL",
        lambda: build_provider(
            AdapterConfig(
                "ollama",
                model=os.environ["THEMI_LIVE_OLLAMA_MODEL"],
                base_url=os.environ.get("THEMI_LIVE_OLLAMA_URL"),
            )
        ),
    )
    return params


async def _retrying(call):
    return await call_with_retry(call, CallKind.BACKGROUND)


@pytest.mark.parametrize("make", _providers())
async def test_plain_reply(make) -> None:
    provider: Provider = make()
    response = await _retrying(
        lambda: provider.chat("Answer in one word.", [Message.user("Say the word: ready")])
    )
    assert response.stop_reason is StopReason.END
    assert "ready" in response.text.lower()


@pytest.mark.parametrize("make", _providers())
async def test_tool_round_trip(make) -> None:
    provider: Provider = make()
    system = "When the user mentions eating, call log_meal, then confirm briefly."
    history = [Message.user("I just had a bowl of soup.")]
    first = await _retrying(lambda: provider.chat(system, history, [LOG_MEAL]))
    assert first.tool_calls, f"{provider.name} didn't call the tool: {first.text!r}"
    call = first.tool_calls[0]
    assert call.name == "log_meal" and "soup" in str(call.arguments).lower()
    history += [first.message, Message.tool_results(ToolResult(call.id, "logged"))]
    second = await _retrying(lambda: provider.chat(system, history, [LOG_MEAL]))
    assert second.text


@pytest.mark.parametrize("make", _providers())
async def test_structured_output(make) -> None:
    provider: Provider = make()
    schema = {
        "type": "object",
        "properties": {"category": {"type": "string", "enum": ["receipt", "noise", "urgent"]}},
        "required": ["category"],
        "additionalProperties": False,
    }
    result = await _retrying(
        lambda: provider.structured(
            "Classify the email.", "Subject: Your Safeway receipt\nTotal $42.10", schema
        )
    )
    assert result.data["category"] == "receipt"
