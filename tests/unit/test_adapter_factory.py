import pytest

from themi.ai import PermanentError
from themi.ai.adapters import (
    AdapterConfig,
    AnthropicProvider,
    GeminiProvider,
    OpenAICompatProvider,
    build_provider,
)
from themi.ai.adapters.openai_compat import LM_STUDIO_URL, OLLAMA_URL
from themi.storage.secrets import Secret


def test_defaults_per_kind() -> None:
    claude = build_provider(AdapterConfig("anthropic", api_key=Secret("k")))
    assert isinstance(claude, AnthropicProvider)
    assert claude.model == "claude-opus-5-5" and claude.server_fallback
    assert not claude.capabilities.audio

    gemini = build_provider(AdapterConfig("gemini", api_key=Secret("k")))
    assert isinstance(gemini, GeminiProvider)
    assert gemini.model == "gemini-3.5-flash-lite" and gemini.capabilities.audio


def test_claude_effort_is_configurable() -> None:
    claude = build_provider(AdapterConfig("anthropic", api_key=Secret("k"), effort="low"))
    assert isinstance(claude, AnthropicProvider) and claude.effort == "low"


@pytest.mark.parametrize(("kind", "url"), [("ollama", OLLAMA_URL), ("lm_studio", LM_STUDIO_URL)])
def test_local_presets(kind: str, url: str) -> None:
    local = build_provider(AdapterConfig(kind, model="qwen-test", supports_tools=False))  # type: ignore[arg-type]
    assert isinstance(local, OpenAICompatProvider)
    assert local.name == kind and local.model == "qwen-test"
    assert not local.capabilities.tools
    assert str(local._client.base_url).rstrip("/") == url


@pytest.mark.parametrize(
    "config",
    [
        AdapterConfig("anthropic"),
        AdapterConfig("gemini"),
        AdapterConfig("ollama"),
        AdapterConfig("openai_compat", model="m"),
    ],
)
def test_incomplete_configs_are_permanent_errors(config: AdapterConfig) -> None:
    with pytest.raises(PermanentError):
        build_provider(config)


def test_timeouts_and_aiohttp_errors_count_as_transport_errors() -> None:
    """google-genai uses aiohttp when it's installed (the OurGroceries extra brings it, so the
    Docker image has it). Its timeouts surface as the built-in TimeoutError, which wasn't
    treated as retryable, so a slow reply skipped the retry and fallback."""
    from themi.ai.adapters._common import transport_exceptions

    errors = transport_exceptions()
    assert TimeoutError in errors
    try:
        import aiohttp
    except ImportError:
        return
    assert aiohttp.ClientError in errors
