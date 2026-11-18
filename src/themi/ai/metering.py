"""Counting what each AI request spends (UC2; the Themi Usage Plan's "AI metering").

The router wraps each backend's provider in `Counted`, so every request that reaches the
provider is counted against that backend's meters, with the model that answered and its
tokens: a retry is a second request, and a hedged call's second copy counts too, since free
tiers count requests sent. A check that fails before anything is sent (a backend that can't
see pictures) raises `CapabilityError` and counts nothing; a 429 counts as refused, not as a
request.

Meters are named by the backend's adapter kind: `<kind>.requests` (chat, structured,
transcription), `<kind>.embeddings` and `<kind>.pictures`; the scope is the backend's id.
The AI provider modules register them, with their limits and prices.
"""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from typing import Any, TypeVar

from themi.ai.adapters.defaults import (
    ANTHROPIC_DEFAULT_MODEL,
    CLOUDFLARE_DEFAULT_IMAGE_MODEL,
    CLOUDFLARE_FALLBACK_IMAGE_MODEL,
    GEMINI_DEFAULT_IMAGE_MODEL,
    OPENAI_DEFAULT_IMAGE_MODEL,
)
from themi.ai.errors import CapabilityError, RetryableError
from themi.ai.provider import DEFAULT_MAX_TOKENS, IMAGE_SIZE, Capabilities, Provider
from themi.ai.types import (
    CallKind,
    ChatResponse,
    Embeddings,
    ImageBlock,
    ImageReference,
    ImageResult,
    Message,
    StructuredResponse,
    ToolSpec,
    Transcription,
    Usage,
)
from themi.usage import Limits, Meter, Price, UsageBook

T = TypeVar("T")

REQUESTS = "requests"
EMBEDDINGS = "embeddings"
PICTURES = "pictures"


def meter_key(kind: str, what: str = REQUESTS) -> str:
    return f"{kind}.{what}"


PACIFIC = "America/Los_Angeles"

# Each provider's meters, which its module registers (`themi.standard.ai_providers`).
# Google stopped publishing per-model free-tier numbers (its page points to AI Studio's
# rate-limit page, per project); 500 a day for flash-lite is what guides report, checked
# 2026-11. Quotas reset at midnight Pacific. Embeddings: no number known.
GEMINI_SOURCE = "third-party guides; AI Studio's rate-limit page has the project's own"
PROVIDER_METERS: dict[str, tuple[Meter, ...]] = {
    "anthropic": (
        Meter(
            meter_key("anthropic"), "Claude", "requests", group="AI", order=30,
            # claude-api skill's model table (cached 2026-11-03): $4 in, $20 out
            prices={ANTHROPIC_DEFAULT_MODEL: Price(input_per_mtok=4.0, output_per_mtok=20.0)},
        ),
    ),
    "gemini": (
        Meter(
            meter_key("gemini"), "Gemini", "requests", group="AI", order=10,
            limits=Limits(per_day=500, resets=PACIFIC, source=GEMINI_SOURCE, checked="2026-11"),
        ),
        Meter(meter_key("gemini", EMBEDDINGS), "Gemini embeddings", "requests", group="AI",
              order=11, limits=Limits(resets=PACIFIC)),
        Meter(
            meter_key("gemini", PICTURES), "Gemini pictures", "pictures", group="AI", order=12,
            # BD4a: no Gemini image model has a free tier; $0.0336 a 1K picture
            prices={GEMINI_DEFAULT_IMAGE_MODEL: Price(per_request=0.0336)},
        ),
    ),
    "cloudflare": (
        Meter(
            meter_key("cloudflare", PICTURES), "Cloudflare pictures", "neurons", group="AI",
            order=20, measure="amount",
            limits=Limits(per_day=10_000, resets="UTC", source="developers.cloudflare.com",
                          checked="2026-11"),
            # BD4c: about 104 neurons a 1024px klein picture, 58 a schnell one
            amounts={CLOUDFLARE_DEFAULT_IMAGE_MODEL: 104, CLOUDFLARE_FALLBACK_IMAGE_MODEL: 58},
        ),
    ),
    "openai_compat": (
        Meter(meter_key("openai_compat"), "Your AI server", "requests", group="AI", order=40),
        Meter(
            meter_key("openai_compat", PICTURES), "OpenAI pictures", "pictures", group="AI",
            order=41,
            # 2026-11: about $0.006 a low-quality 1024px picture (OpenAI's listed rate)
            prices={OPENAI_DEFAULT_IMAGE_MODEL: Price(per_request=0.006)},
        ),
    ),
    "ollama": (Meter(meter_key("ollama"), "Ollama", "requests", group="AI", order=42),),
    "lm_studio": (Meter(meter_key("lm_studio"), "LM Studio", "requests", group="AI", order=43),),
}  # fmt: skip


class Counted:
    """A provider whose requests are counted in the usage book."""

    def __init__(self, provider: Provider, usage: UsageBook, kind: str, scope: int | str) -> None:
        self._provider = provider
        self._usage = usage
        self._kind = kind
        self._scope = str(scope)

    @property
    def name(self) -> str:
        return self._provider.name

    @property
    def model(self) -> str:
        return self._provider.model

    @property
    def capabilities(self) -> Capabilities:
        return self._provider.capabilities

    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.INTERACTIVE,
    ) -> ChatResponse:
        call = self._provider.chat(system, messages, tools, max_tokens=max_tokens, kind=kind)
        return await self._counted(REQUESTS, call)

    async def structured(
        self,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.BACKGROUND,
        images: Sequence[ImageBlock] = (),
    ) -> StructuredResponse:
        if images:
            call = self._provider.structured(
                system, prompt, schema, max_tokens=max_tokens, kind=kind, images=images
            )
        else:  # as the router asked before F34m, for fakes that don't take images
            call = self._provider.structured(
                system, prompt, schema, max_tokens=max_tokens, kind=kind
            )
        return await self._counted(REQUESTS, call)

    async def transcribe(
        self, audio: bytes, mime_type: str, *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Transcription:
        return await self._counted(REQUESTS, self._provider.transcribe(audio, mime_type, kind=kind))

    async def embed(
        self, texts: Sequence[str], *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Embeddings:
        return await self._counted(EMBEDDINGS, self._provider.embed(texts, kind=kind))

    async def image(
        self,
        prompt: str,
        size: str = IMAGE_SIZE,
        *,
        kind: CallKind = CallKind.BACKGROUND,
        references: Sequence[ImageReference] = (),
    ) -> ImageResult:
        call = self._provider.image(prompt, size, kind=kind, references=references)
        return await self._counted(PICTURES, call)

    async def _counted(self, what: str, call: Awaitable[T]) -> T:
        """Counted as it's sent, so a hedge's cancelled copy counts too; the tokens are
        added when the answer comes. The provider turning the call down itself (a
        `CapabilityError`) or a 429 takes the request back; a 429 counts as refused."""
        key = meter_key(self._kind, what)
        count = self._usage.count
        count(key, scope=self._scope, model=self.model)
        try:
            result = await call
        except CapabilityError:
            count(key, -1, scope=self._scope, model=self.model)  # nothing was sent
            raise
        except RetryableError as exc:
            if exc.status == 429:
                count(key, -1, scope=self._scope, model=self.model)
                count(f"{key}.refused", scope=self._scope, model=self.model)
            raise
        usage = getattr(result, "usage", None)
        if isinstance(usage, Usage) and (usage.input_tokens or usage.output_tokens):
            count(
                key,
                0,
                scope=self._scope,
                model=self.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        return result
