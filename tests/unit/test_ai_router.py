import logging
from datetime import datetime

import pytest

from tests.fakes.scripted_provider import ScriptedProvider
from tests.fixtures.family import SeededFamily
from themi.ai import Capabilities, Message, RefusalError, StopReason, ToolSpec
from themi.ai.adapters import AdapterConfig
from themi.ai.router import AIRouter, AllProvidersFailed, Deferred
from themi.ai.settings import AISettingsStore, AITask, RouteEntry
from themi.ai.types import CallKind
from themi.storage.secrets import Cipher, Secret, generate_key

ERIN_CLAUDE = "sk-ant-erin-0000000000000000000000"
ERIN_GEMINI = "AIza-erin-gemini-key-000000000000000000"
HUSBAND_CLAUDE = "sk-ant-husband-00000000000000000000"

LOG_MEAL = ToolSpec(
    "log_meal",
    "Record a meal",
    {
        "type": "object",
        "properties": {"description": {"type": "string"}},
        "required": ["description"],
        "additionalProperties": False,
    },
)


class Factory:
    """Builds ScriptedProviders keyed by API key (or model, for keyless local servers)."""

    def __init__(self) -> None:
        self.providers: dict[str, ScriptedProvider] = {}
        self.configs: list[AdapterConfig] = []

    def __call__(self, config: AdapterConfig) -> ScriptedProvider:
        self.configs.append(config)
        if config.kind in ("anthropic", "gemini") and config.api_key is None:
            from themi.ai import PermanentError

            raise PermanentError(f"{config.kind} needs an API key")
        key = config.api_key.reveal() if config.api_key else config.model
        if key not in self.providers:
            self.providers[key] = ScriptedProvider(name=config.kind, model=config.resolved_model)
        return self.providers[key]

    def provider(self, key: str, **kwargs) -> ScriptedProvider:
        if key not in self.providers:
            self.providers[key] = ScriptedProvider(**kwargs)
        return self.providers[key]


class NoSleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


@pytest.fixture
def ai(family: SeededFamily) -> AISettingsStore:
    return AISettingsStore(family.db, Cipher(generate_key()))


@pytest.fixture
def factory() -> Factory:
    return Factory()


@pytest.fixture
def router(ai: AISettingsStore, factory: Factory) -> AIRouter:
    return AIRouter(ai, sleep=NoSleep(), factory=factory)


def two_step_chain(family: SeededFamily, ai: AISettingsStore) -> None:
    erin = family.erin
    claude = ai.add_backend(erin, erin.id, "Claude", "anthropic", api_key=Secret(ERIN_CLAUDE))
    gemini = ai.add_backend(erin, erin.id, "Gemini", "gemini", api_key=Secret(ERIN_GEMINI))
    for task in AITask:
        ai.set_chain(erin, erin.id, task, [RouteEntry(claude.id), RouteEntry(gemini.id)])
    husband = family.husband
    his = ai.add_backend(husband, husband.id, "Claude", "anthropic", api_key=Secret(HUSBAND_CLAUDE))
    ai.set_chain(husband, husband.id, AITask.CONVERSATION, [RouteEntry(his.id)])


def hello() -> list[Message]:
    return [Message.user("hello")]


async def test_primary_answers_when_healthy(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).queue_text("Hi from Claude")
    response = await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    assert response.text == "Hi from Claude"
    assert [c.api_key.reveal() for c in factory.configs if c.api_key] == [ERIN_CLAUDE]


async def test_falls_back_after_retries_run_out(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).fail(3, status=529)
    factory.provider(ERIN_GEMINI).queue_text("Hi from Gemini")
    response = await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    assert response.text == "Hi from Gemini"
    assert len(factory.providers[ERIN_CLAUDE].requests) == 3  # interactive attempts


async def test_a_permanent_error_skips_straight_to_the_next_backend(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).fail(1, status=401)
    factory.provider(ERIN_GEMINI).queue_text("ok")
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    assert len(factory.providers[ERIN_CLAUDE].requests) == 1


async def test_keys_never_cross_members(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).fail(3, status=503)
    factory.provider(ERIN_GEMINI).queue_text("for erin")
    factory.provider(HUSBAND_CLAUDE).queue_text("for him")
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    erin_keys = {c.api_key.reveal() for c in factory.configs if c.api_key}
    factory.configs.clear()
    await router.client_for(family.husband.id, AITask.CONVERSATION).chat("s", hello())
    husband_keys = {c.api_key.reveal() for c in factory.configs if c.api_key}
    assert erin_keys == {ERIN_CLAUDE, ERIN_GEMINI}
    assert husband_keys == {HUSBAND_CLAUDE}


async def test_interactive_failure_of_every_backend(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).fail(3, status=503)
    factory.provider(ERIN_GEMINI).fail(3, status=503)
    with pytest.raises(AllProvidersFailed) as info:
        await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    assert [label for label, _ in info.value.errors] == ["Claude", "Gemini"]
    assert not info.value.needs_setup


async def test_background_failure_is_deferred_with_a_retry_hint(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).fail(6, status=503, op="structured")
    factory.provider(ERIN_GEMINI).fail(1, status=429, retry_after=3600, op="structured")
    with pytest.raises(Deferred) as info:
        await router.client_for(family.erin.id, AITask.EMAIL_TRIAGE).structured(
            "s", "classify", {"type": "object"}, kind=CallKind.BACKGROUND
        )
    assert info.value.retry_after == 3600


async def test_new_member_without_a_key_needs_setup(family: SeededFamily, router: AIRouter) -> None:
    with pytest.raises(AllProvidersFailed) as info:
        await router.client_for(family.husband.id, AITask.CONVERSATION).chat("s", hello())
    assert info.value.needs_setup
    assert "Gemini (free tier)" in str(info.value)


async def test_refusal_tries_the_next_model_then_surfaces(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).queue_refusal("cyber")
    factory.provider(ERIN_GEMINI).queue_text("answered")
    response = await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    assert response.text == "answered"

    factory.provider(ERIN_CLAUDE).queue_refusal("cyber")
    factory.provider(ERIN_GEMINI).queue_refusal("safety")
    with pytest.raises(RefusalError):
        await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())


async def test_open_breaker_skips_a_backend_without_calling_it(
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
    gemini.queue_text("one").queue_text("two")
    client = router.client_for(family.erin.id, AITask.CONVERSATION)
    await client.chat("s", hello())  # 3 failures, then Gemini
    claude.fail(2, status=503)
    await client.chat("s", hello())  # 2 more failures: breaker opens mid-retries
    assert len(claude.requests) == 5
    gemini.queue_text("three")
    await client.chat("s", hello())
    assert len(claude.requests) == 5  # skipped while open


async def test_tools_on_a_model_without_tool_support_use_json_mode(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    erin = family.erin
    local = ai.add_backend(erin, erin.id, "Laptop", "ollama", model="tiny", supports_tools=False)
    ai.set_chain(erin, erin.id, AITask.CONVERSATION, [RouteEntry(local.id)])
    provider = factory.provider(
        "tiny", name="ollama", model="tiny", capabilities=Capabilities(tools=False, structured=True)
    )
    provider.queue_structured(
        {
            "reply": "Logged.",
            "actions": [{"tool": "log_meal", "arguments": {"description": "soup"}}],
        }
    )
    response = await router.client_for(erin.id, AITask.CONVERSATION).chat("s", hello(), [LOG_MEAL])
    assert response.stop_reason is StopReason.TOOL_USE
    assert response.tool_calls[0].arguments == {"description": "soup"}
    assert [r.op for r in provider.requests] == ["structured"]


async def test_transcription_skips_backends_without_audio(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE, capabilities=Capabilities(audio=False))
    factory.provider(ERIN_GEMINI).queue_transcription("had soup")
    result = await router.client_for(family.erin.id, AITask.TRANSCRIPTION).transcribe(
        b"o", "audio/ogg"
    )
    assert result.text == "had soup"
    assert factory.providers[ERIN_CLAUDE].requests == []


async def test_on_retry_hook_reaches_the_caller(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).fail(1, status=503).queue_text("ok")
    seen: list[int] = []
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat(
        "s", hello(), on_retry=lambda attempt, error, wait: seen.append(attempt)
    )
    assert seen == [1]


async def test_connection_test(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).queue_text("OK")
    good = await router.test_connection(family.erin.id, AITask.CONVERSATION)
    assert good.ok and good.label == "Claude"

    factory.provider(ERIN_GEMINI).fail(1, status=403)
    bad = await router.test_connection(family.erin.id, AITask.CONVERSATION, position=1)
    assert not bad.ok and bad.label == "Gemini" and "403" in bad.detail
    assert ERIN_GEMINI not in bad.detail

    missing = await router.test_connection(family.erin.id, AITask.CONVERSATION, position=5)
    assert not missing.ok


async def test_keys_stay_out_of_logs_and_errors(
    family: SeededFamily,
    ai: AISettingsStore,
    factory: Factory,
    router: AIRouter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).fail(3, status=503)
    factory.provider(ERIN_GEMINI).fail(1, status=401)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(AllProvidersFailed) as info:
        await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    for key in (ERIN_CLAUDE, ERIN_GEMINI):
        assert key not in caplog.text
        assert key not in str(info.value) and key not in repr(info.value.errors)


async def test_each_call_is_recorded_with_its_waits(
    family: SeededFamily, ai: AISettingsStore, factory: Factory, router: AIRouter
) -> None:
    """Bug #29: a reply took a minute and nothing said why. Each call now records its time,
    its waits for a busy provider and its retries."""
    two_step_chain(family, ai)
    factory.provider(ERIN_CLAUDE).fail(1, status=429, retry_after=15)
    factory.provider(ERIN_CLAUDE).queue_text("Hi")
    await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    (row,) = family.db.query("SELECT * FROM ai_calls")
    assert (row["member_id"], row["task"], row["backend"]) == (
        family.erin.id,
        "conversation",
        "Claude",
    )
    assert (row["retries"], row["waited"], row["last_status"], row["ok"]) == (1, 15.0, 429, 1)

    factory.provider(ERIN_CLAUDE).fail(3, status=529)
    factory.provider(ERIN_GEMINI).fail(3, status=529)
    with pytest.raises(AllProvidersFailed):
        await router.client_for(family.erin.id, AITask.CONVERSATION).chat("s", hello())
    last = family.db.query("SELECT * FROM ai_calls ORDER BY id DESC LIMIT 1")[0]
    assert (last["ok"], last["last_status"]) == (0, 529)
