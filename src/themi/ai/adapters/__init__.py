"""Build a provider from a stored configuration.

`AdapterConfig` is what the router (prompt 06) keeps per member and task.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from themi.ai.adapters.anthropic import DEFAULT_EFFORT, AnthropicProvider
from themi.ai.adapters.anthropic import DEFAULT_MODEL as ANTHROPIC_DEFAULT_MODEL
from themi.ai.adapters.gemini import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from themi.ai.adapters.gemini import GeminiProvider
from themi.ai.adapters.openai_compat import LM_STUDIO_URL, OLLAMA_URL, OpenAICompatProvider
from themi.ai.errors import PermanentError
from themi.ai.provider import Capabilities, Provider
from themi.storage.secrets import Secret

AdapterKind = Literal["anthropic", "gemini", "ollama", "lm_studio", "openai_compat"]

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": ANTHROPIC_DEFAULT_MODEL,
    "gemini": GEMINI_DEFAULT_MODEL,
}


@dataclass(frozen=True)
class AdapterConfig:
    kind: AdapterKind
    model: str = ""
    api_key: Secret | None = None
    base_url: str | None = None
    timeout: float = 60.0
    # Capability overrides for OpenAI-compatible servers, whose models vary.
    # Claude never takes audio; Gemini always does.
    supports_tools: bool = True
    supports_structured: bool = True
    supports_audio: bool = False
    # Claude only: thinking effort (low, medium, high, xhigh, max).
    effort: str | None = None

    @property
    def resolved_model(self) -> str:
        return self.model or DEFAULT_MODELS.get(self.kind, "")


def build_provider(config: AdapterConfig) -> Provider:
    model = config.resolved_model
    if not model:
        raise PermanentError(f"no model configured for {config.kind}")
    if config.kind == "anthropic":
        if config.api_key is None:
            raise PermanentError("Claude needs an API key")
        return AnthropicProvider(
            config.api_key,
            model,
            base_url=config.base_url,
            timeout=config.timeout,
            effort=config.effort or DEFAULT_EFFORT,
        )
    if config.kind == "gemini":
        if config.api_key is None:
            raise PermanentError("Gemini needs an API key")
        return GeminiProvider(
            config.api_key,
            model,
            base_url=config.base_url,
            timeout=config.timeout,
        )
    capabilities = Capabilities(
        tools=config.supports_tools,
        structured=config.supports_structured,
        audio=config.supports_audio,
    )
    default_urls = {"ollama": OLLAMA_URL, "lm_studio": LM_STUDIO_URL}
    base_url = config.base_url or default_urls.get(config.kind)
    if base_url is None:
        raise PermanentError("an OpenAI-compatible provider needs a base URL")
    return OpenAICompatProvider(
        model,
        base_url=base_url,
        api_key=config.api_key,
        name=config.kind,
        capabilities=capabilities,
        timeout=config.timeout,
    )


__all__ = [
    "AdapterConfig",
    "AdapterKind",
    "AnthropicProvider",
    "GeminiProvider",
    "OpenAICompatProvider",
    "build_provider",
]
