"""The router driving real adapters over HTTP: retries, fallback and key isolation on the wire."""

import pytest

from tests.fakes.http_ai import FakeAIServer, anthropic_error, gemini_text
from tests.fixtures.family import SeededFamily
from themi.ai import Message
from themi.ai.router import AIRouter
from themi.ai.settings import AISettingsStore, AITask, RouteEntry
from themi.storage.secrets import Cipher, Secret, generate_key

ERIN_CLAUDE = "sk-ant-erin-wire-test-000000000000"
ERIN_GEMINI = "AIzaErinWireTestKey00000000000000000000"
HUSBAND_CLAUDE = "sk-ant-husband-wire-test-0000000000"


async def no_sleep(seconds: float) -> None:
    return None


@pytest.fixture
def router(family: SeededFamily, fake_ai: FakeAIServer) -> AIRouter:
    ai = AISettingsStore(family.db, Cipher(generate_key()))
    erin, husband = family.erin, family.husband
    claude = ai.add_backend(
        erin,
        erin.id,
        "Claude",
        "anthropic",
        api_key=Secret(ERIN_CLAUDE),
        base_url=fake_ai.url,
        timeout=2,
    )
    gemini = ai.add_backend(
        erin,
        erin.id,
        "Gemini",
        "gemini",
        api_key=Secret(ERIN_GEMINI),
        base_url=fake_ai.url,
        timeout=2,
    )
    ai.set_chain(erin, erin.id, AITask.CONVERSATION, [RouteEntry(claude.id), RouteEntry(gemini.id)])
    his = ai.add_backend(
        husband,
        husband.id,
        "Claude",
        "anthropic",
        api_key=Secret(HUSBAND_CLAUDE),
        base_url=fake_ai.url,
        timeout=2,
    )
    ai.set_chain(husband, husband.id, AITask.CONVERSATION, [RouteEntry(his.id)])
    return AIRouter(ai, sleep=no_sleep)


def sent_key(headers: dict[str, str]) -> str:
    if "x-goog-api-key" in headers:
        return headers["x-goog-api-key"]
    return headers.get("x-api-key") or headers["authorization"].removeprefix("Bearer ")


async def test_overloaded_claude_falls_back_to_erins_gemini(
    family: SeededFamily, fake_ai: FakeAIServer, router: AIRouter
) -> None:
    for _ in range(3):
        fake_ai.queue(anthropic_error("overloaded_error"), status=529, headers={"retry-after": "1"})
    fake_ai.queue(gemini_text("Hi Erin, from Gemini"))

    response = await router.client_for(family.erin.id, AITask.CONVERSATION).chat(
        "Be warm.", [Message.user("hello")]
    )
    assert response.text == "Hi Erin, from Gemini"
    assert response.provider == "gemini"

    keys = [sent_key(r.headers) for r in fake_ai.requests]
    assert keys == [ERIN_CLAUDE, ERIN_CLAUDE, ERIN_CLAUDE, ERIN_GEMINI]
    assert all(HUSBAND_CLAUDE not in str(r.headers) for r in fake_ai.requests)
