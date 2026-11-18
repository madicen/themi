"""UC2: the router counts every request a backend sends, with its model and tokens."""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.fakes.scripted_provider import ScriptedProvider
from tests.fixtures.family import SeededFamily
from tests.unit.test_ai_router import (
    ERIN_CLAUDE,
    ERIN_GEMINI,
    Factory,
    NoSleep,
    hello,
    two_step_chain,
)
from themi.ai import Capabilities, ImageBlock, Message, TextBlock
from themi.ai.adapters import AdapterConfig
from themi.ai.router import AIRouter
from themi.ai.settings import AISettingsStore, AITask, RouteEntry
from themi.storage.secrets import Cipher, Secret, generate_key
from themi.usage import Meter, Price


@pytest.fixture
def ai(family: SeededFamily) -> AISettingsStore:
    return AISettingsStore(family.db, Cipher(generate_key()))


@pytest.fixture
def factory() -> Factory:
    return Factory()


@pytest.fixture
def router(ai: AISettingsStore, factory: Factory) -> AIRouter:
    return AIRouter(ai, sleep=NoSleep(), factory=factory)


def rows(family: SeededFamily) -> list[tuple[str, str, int, int, int]]:
    return [
        (r["meter"], r["model"], r["count"], r["input_tokens"], r["output_tokens"])
        for r in family.db.query("SELECT * FROM usage_daily ORDER BY meter, model")
    ]


async def test_one_chat_counts_one_request_with_its_tokens(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    frozen_clock: datetime,
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).queue_text("hi")
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    claude = ai.resolve(family.erin.id, AITask.CONVERSATION)[0]
    model = factory.provider(ERIN_CLAUDE).model
    assert rows(family) == [("anthropic.requests", model, 1, 10, 10)]
    assert family.db.scalar("SELECT scope FROM usage_daily") == str(claude.backend_id)


async def test_a_retry_is_a_second_request(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    frozen_clock: datetime,
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).fail(1, status=503).queue_text("hi")
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    assert router.usage.today("anthropic.requests").count == 2


async def test_a_429_counts_as_refused_not_as_a_request(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    frozen_clock: datetime,
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).fail(1, status=429).queue_text("hi")
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    assert router.usage.today("anthropic.requests.refused").count == 1
    assert router.usage.today("anthropic.requests").count == 1


async def test_both_halves_of_a_hedge_count(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    frozen_clock: datetime,
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).take(30).queue_text("Hi")
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    assert router.usage.today("anthropic.requests").count == 2


async def test_an_open_breaker_counts_nothing_for_the_skipped_backend(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    frozen_clock: datetime,
) -> None:
    two_step_chain(family, ai)
    claude = factory.provider(ERIN_CLAUDE)
    gemini = factory.provider(ERIN_GEMINI)
    claude.fail(5, status=503)
    gemini.queue_text("one").queue_text("two").queue_text("three")
    client = router.client_for(family.erin.id, AITask.CONVERSATION)
    await client.chat("s", hello())
    await client.chat("s", hello())  # the breaker opens
    before = router.usage.today("anthropic.requests").count
    await client.chat("s", hello())
    assert before == 5
    assert router.usage.today("anthropic.requests").count == 5
    assert router.usage.today("gemini.requests").count == 3


async def test_a_backend_that_cant_take_the_call_counts_nothing(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    frozen_clock: datetime,
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE, capabilities=Capabilities(images=False))
    factory.provider(ERIN_GEMINI, capabilities=Capabilities(images=True)).queue_text("milk")
    picture = Message("user", (TextBlock("add these"), ImageBlock(b"png", "image/png")))
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", [picture])
    assert router.usage.today("anthropic.requests").count == 0
    assert router.usage.today("gemini.requests").count == 1


async def test_two_members_on_their_own_keys_get_a_row_each(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    frozen_clock: datetime,
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).queue_text("for erin")
    factory.provider("sk-ant-husband-00000000000000000000").queue_text("for him")
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    await router.client_for(family.husband.id, AITask.CONVERSATION).chat("s", hello())
    assert len(router.usage.scopes("anthropic.requests")) == 2


async def test_embeddings_and_pictures_have_their_own_meters(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    frozen_clock: datetime,
) -> None:
    erin = family.erin
    gemini = ai.add_backend(erin, erin.id, "Gemini", "gemini", api_key=Secret(ERIN_GEMINI))
    for task in (AITask.EMBEDDING, AITask.STEP_IMAGE):
        ai.set_chain(erin, erin.id, task, [RouteEntry(gemini.id)])
    gemini_fake = factory.provider(ERIN_GEMINI)
    gemini_fake.queue_image()
    gemini_fake.embed_with = lambda text: [1.0, 0.0]
    await router.client_for(erin.id, AITask.EMBEDDING).embed(["oat milk"])
    family.db.execute("UPDATE members SET image_daily_cap = 5 WHERE id = ?", (erin.id,))
    await router.client_for(erin.id, AITask.STEP_IMAGE).image("a chameleon")
    assert router.usage.today("gemini.embeddings").count == 1
    assert router.usage.today("gemini.pictures").count == 1


async def test_a_picture_model_adds_its_amount(
    family: SeededFamily, ai: AISettingsStore, frozen_clock: datetime
) -> None:
    erin = family.erin
    cf = ai.add_backend(erin, erin.id, "Cloudflare", "cloudflare", api_key=Secret("cf-key"))
    ai.set_chain(erin, erin.id, AITask.STEP_IMAGE, [RouteEntry(cf.id)])
    family.db.execute("UPDATE members SET image_daily_cap = 5 WHERE id = ?", (erin.id,))
    provider = ScriptedProvider(name="cloudflare", model="klein").queue_image()

    def build(config: AdapterConfig) -> ScriptedProvider:
        return provider

    router = AIRouter(ai, sleep=NoSleep(), factory=build)
    router.usage.add(Meter("cloudflare.pictures", "Cloudflare", "neurons", amounts={"klein": 104}))
    await router.client_for(erin.id, AITask.STEP_IMAGE).image("a chameleon")
    assert router.usage.today("cloudflare.pictures").amount == 104


async def test_a_priced_backend_gets_an_estimate(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    frozen_clock: datetime,
) -> None:
    two_step_chain(family, ai)
    model = factory.provider(ERIN_CLAUDE).model
    router.usage.add(
        Meter("anthropic.requests", "Claude", "requests",
              prices={model: Price(input_per_mtok=4.0, output_per_mtok=20.0)})
    )  # fmt: skip
    factory.provider(ERIN_CLAUDE).queue_text("hi")
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    assert router.usage.estimate("anthropic.requests") == pytest.approx(10 * 4e-6 + 10 * 20e-6)


async def test_the_connection_test_counts_too(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    frozen_clock: datetime,
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).queue_text("pong")
    result = await router.test_connection(family.erin.id, AITask.CONVERSATION)
    assert result.ok
    assert router.usage.today("anthropic.requests").count == 1


def test_the_provider_modules_register_their_meters(family: SeededFamily) -> None:
    from tests.fakes.modules import module_context
    from themi.standard.ai_providers import CloudflareModule, GeminiModule

    ctx = module_context(family.store)
    ctx.load(GeminiModule(), CloudflareModule())
    usage = ctx.services.usage
    gemini = usage.limit_for("gemini.requests")
    assert gemini is not None and gemini.per_day == 500
    assert usage.zone("gemini.requests").key == "America/Los_Angeles"
    assert usage.limit_for("gemini.embeddings") is None
    cloudflare = usage.meters["cloudflare.pictures"]
    assert cloudflare.measure == "amount" and cloudflare.module == "cloudflare"
    assert usage.limit_for("cloudflare.pictures").per_day == 10_000  # type: ignore[union-attr]
