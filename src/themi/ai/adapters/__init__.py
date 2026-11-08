"""Build a provider from a stored configuration.

`AdapterConfig` is what the router (prompt 06) keeps per member and task.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from themi.ai.adapters.defaults import (
    ANTHROPIC_DEFAULT_EFFORT,
    ANTHROPIC_DEFAULT_MODEL,
    CLOUDFLARE_DEFAULT_IMAGE_MODEL,
    GEMINI_DEFAULT_MODEL,
    LM_STUDIO_URL,
    OLLAMA_URL,
)
from themi.ai.errors import PermanentError
from themi.ai.provider import Capabilities, Provider
from themi.storage.secrets import Secret

if TYPE_CHECKING:
    from themi.ai.adapters.anthropic import AnthropicProvider
    from themi.ai.adapters.gemini import GeminiProvider
    from themi.ai.adapters.openai_compat import OpenAICompatProvider

AdapterKind = Literal["anthropic", "gemini", "ollama", "lm_studio", "openai_compat", "cloudflare"]

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": ANTHROPIC_DEFAULT_MODEL,
    "gemini": GEMINI_DEFAULT_MODEL,
    "cloudflare": CLOUDFLARE_DEFAULT_IMAGE_MODEL,  # pictures only
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
    supports_images: bool = False  # F34g; switched on the AI page (F34gb)
    # Claude only: thinking effort (low, medium, high, xhigh, max).
    effort: str | None = None

    @property
    def resolved_model(self) -> str:
        return self.model or DEFAULT_MODELS.get(self.kind, "")


Builder = Callable[[AdapterConfig], Provider]


def build_anthropic(config: AdapterConfig) -> Provider:
    if config.api_key is None:
        raise PermanentError("Claude needs an API key")
    from themi.ai.adapters.anthropic import AnthropicProvider

    return AnthropicProvider(
        config.api_key,
        config.resolved_model,
        base_url=config.base_url,
        timeout=config.timeout,
        effort=config.effort or ANTHROPIC_DEFAULT_EFFORT,
    )


def build_gemini(config: AdapterConfig) -> Provider:
    if config.api_key is None:
        raise PermanentError("Gemini needs an API key")
    from themi.ai.adapters.gemini import GeminiProvider

    return GeminiProvider(
        config.api_key, config.resolved_model, base_url=config.base_url, timeout=config.timeout
    )


def build_cloudflare(config: AdapterConfig) -> Provider:
    if config.api_key is None or not config.base_url:
        raise PermanentError("Cloudflare needs an API token and the account ID")
    from themi.ai.adapters.cloudflare import CloudflareProvider

    try:
        return CloudflareProvider(
            config.api_key, config.base_url, config.resolved_model, timeout=config.timeout
        )
    except ValueError as exc:
        raise PermanentError(str(exc)) from exc


def build_openai_compat(config: AdapterConfig) -> Provider:
    """Ollama, LM Studio, or any other OpenAI-compatible server."""
    capabilities = Capabilities(
        tools=config.supports_tools,
        structured=config.supports_structured,
        audio=config.supports_audio,
        images=config.supports_images,
    )
    default_urls = {"ollama": OLLAMA_URL, "lm_studio": LM_STUDIO_URL}
    base_url = config.base_url or default_urls.get(config.kind)
    if base_url is None:
        raise PermanentError("an OpenAI-compatible provider needs a base URL")
    from themi.ai.adapters.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(
        config.resolved_model,
        base_url=base_url,
        api_key=config.api_key,
        name=config.kind,
        capabilities=capabilities,
        timeout=config.timeout,
    )


# CR19: each provider's builder, by kind. A Themi's AI provider modules register theirs.
BUILDERS: dict[str, Builder] = {
    "anthropic": build_anthropic,
    "gemini": build_gemini,
    "cloudflare": build_cloudflare,
    "ollama": build_openai_compat,
    "lm_studio": build_openai_compat,
    "openai_compat": build_openai_compat,
}


def build_provider(config: AdapterConfig, builders: dict[str, Builder] | None = None) -> Provider:
    """The provider a stored configuration describes. `builders`: the loaded AI provider
    modules' (CR19); every kind when not given."""
    if not config.resolved_model:
        raise PermanentError(f"no model configured for {config.kind}")
    builder = (BUILDERS if builders is None else builders).get(config.kind)
    if builder is None:
        raise PermanentError(f"{config.kind} isn't one of this Themi's AI providers")
    return builder(config)


# The SDKs load only when a provider is built (or one of these is imported by name),
# so code that just reads AI settings starts quickly.
_PROVIDERS = {
    "AnthropicProvider": "themi.ai.adapters.anthropic",
    "CloudflareProvider": "themi.ai.adapters.cloudflare",
    "GeminiProvider": "themi.ai.adapters.gemini",
    "OpenAICompatProvider": "themi.ai.adapters.openai_compat",
}


def __getattr__(name: str) -> Any:
    if name in _PROVIDERS:
        import importlib

        return getattr(importlib.import_module(_PROVIDERS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BUILDERS",
    "AdapterConfig",
    "AdapterKind",
    "AnthropicProvider",
    "Builder",
    "GeminiProvider",
    "OpenAICompatProvider",
    "build_provider",
]
