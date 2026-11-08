"""CR19: each AI provider as a module that registers its adapter. A Themi needs at least
one; a member then sets up backends of the loaded kinds on the AI page, with their keys.

- `claude`: Anthropic's Claude.
- `gemini`: Google's Gemini (the free tier is the default backend).
- `openai_compatible`: Ollama, LM Studio, or any other OpenAI-compatible server.
- `cloudflare`: Cloudflare Workers AI, for pictures only.
"""

from __future__ import annotations

from typing import ClassVar

from themi.ai.router import ProviderFactory, builders_for
from themi.modules import Module, ModuleContext


class AIProviderModule(Module):
    kind = "ai"
    adapters: ClassVar[dict[str, ProviderFactory]] = {}

    def install(self, ctx: ModuleContext) -> None:
        for adapter_kind, builder in self.adapters.items():
            ctx.ai_adapter(adapter_kind, builder)


class ClaudeModule(AIProviderModule):
    """Anthropic's Claude, with a member's own API key."""

    name = "claude"
    title = "Claude (Anthropic)"
    summary = "Claude answers, with each person's own Anthropic API key."
    cost = "Paid, by use"
    adapters: ClassVar[dict[str, ProviderFactory]] = builders_for("anthropic")


class GeminiModule(AIProviderModule):
    """Google's Gemini: the free tier is every member's first backend."""

    name = "gemini"
    title = "Gemini (Google)"
    summary = "Google's Gemini answers. Its free tier is everyone's first choice."
    cost = "Free tier is enough to start"
    adapters: ClassVar[dict[str, ProviderFactory]] = builders_for("gemini")


class OpenAICompatibleModule(AIProviderModule):
    """Ollama and LM Studio on this machine, or another OpenAI-compatible server."""

    name = "openai_compatible"
    title = "Your own AI server"
    summary = "Ollama or LM Studio on your own computer, or another OpenAI-compatible server."
    cost = "Free on your own computer"
    adapters: ClassVar[dict[str, ProviderFactory]] = builders_for(
        "ollama", "lm_studio", "openai_compat"
    )


class CloudflareModule(AIProviderModule):
    """Cloudflare Workers AI's free picture model."""

    name = "cloudflare"
    title = "Cloudflare Workers AI"
    summary = "A free picture model, for making pictures."
    cost = "Free plan is enough"
    adapters: ClassVar[dict[str, ProviderFactory]] = builders_for("cloudflare")


AI_PROVIDERS: tuple[type[AIProviderModule], ...] = (
    ClaudeModule,
    GeminiModule,
    OpenAICompatibleModule,
    CloudflareModule,
)
