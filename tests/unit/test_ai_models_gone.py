"""F61c (bug #267): a model the provider says isn't found (a 404) is skipped from then on,
said once, and shown on the backend's settings, until the model is changed."""

from __future__ import annotations

from tests.fixtures.family import SeededFamily
from tests.unit.test_ai_router import (
    ERIN_CLAUDE,
    ERIN_GEMINI,
    Factory,
    ai,
    factory,
    hello,
    router,
    two_step_chain,
)
from themi.ai import PermanentError
from themi.ai.router import AIRouter
from themi.ai.settings import AISettingsStore, AITask, ResolvedEntry

__all__ = ["ai", "factory", "router"]  # the fixtures

NOT_FOUND = PermanentError(
    "gemini returned 404 NOT_FOUND: models/gemini-3.1-flash-lite-preview is not found",
    status=404,
)


async def test_a_model_not_found_is_skipped_and_said_once(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    told: list[tuple[int, str]] = []

    async def listener(member_id: int, entry: ResolvedEntry) -> None:
        told.append((member_id, entry.label))

    router.gone_listeners.append(listener)
    claude, gemini = factory.provider(ERIN_CLAUDE), factory.provider(ERIN_GEMINI)
    claude.queue_error(NOT_FOUND).queue_text("unused")
    gemini.queue_text("From Gemini").queue_text("Gemini again")
    client = router.client_for(family.erin.id, AITask.CONVERSATION)
    assert (await client.chat("s", hello())).text == "From Gemini"
    assert (await client.chat("s", hello())).text == "Gemini again"  # Claude not asked
    assert len(claude.requests) == 1
    assert told == [(family.erin.id, "Claude")]
    (backend,) = [b for b in ai.backends(family.erin.id) if b.label == "Claude"]
    assert router.gone_models(backend.id) == [""]


async def test_another_error_isnt_a_model_gone(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    claude = factory.provider(ERIN_CLAUDE)
    claude.queue_error(PermanentError("bad request", status=400)).queue_text("Claude's back")
    factory.provider(ERIN_GEMINI).queue_text("From Gemini")
    client = router.client_for(family.erin.id, AITask.CONVERSATION)
    await client.chat("s", hello())
    assert (await client.chat("s", hello())).text == "Claude's back"


async def test_changing_the_model_asks_it_again(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    claude = factory.provider(ERIN_CLAUDE)
    claude.queue_error(NOT_FOUND).queue_text("The new model answers")
    factory.provider(ERIN_GEMINI).queue_text("From Gemini")
    client = router.client_for(family.erin.id, AITask.CONVERSATION)
    await client.chat("s", hello())
    (backend,) = [b for b in ai.backends(family.erin.id) if b.label == "Claude"]
    ai.update_backend(family.erin, backend.id, model="claude-newer")
    assert (await client.chat("s", hello())).text == "The new model answers"
