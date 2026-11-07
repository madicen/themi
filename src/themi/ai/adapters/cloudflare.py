"""Cloudflare Workers AI, for pictures only (BD4a's follow-up, 2026-11-06).

Its free tier is 10,000 "neurons" a day per account, with no card. FLUX.1 [schnell]
costs 4.8 neurons per 512x512 tile and 9.6 per step (Cloudflare's pricing page, checked
2026-11-06), so a 1024x1024 picture at 4 steps is about 58 neurons: some 170 a day free.

    POST https://api.cloudflare.com/client/v4/accounts/<account id>/ai/run/<model>
    Authorization: Bearer <API token>
    {"prompt": "...", "steps": 4}  ->  {"result": {"image": "<base64 JPEG>"}, "success": true}

The backend's address is the account ID (or a full `.../accounts/<id>/ai` URL); its key is
an API token with the Workers AI permission. Chat, structured output, audio and
embeddings aren't offered here: the router moves on to the next backend.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

import httpx

from themi.ai.adapters.defaults import CLOUDFLARE_DEFAULT_IMAGE_MODEL
from themi.ai.errors import (
    CapabilityError,
    MalformedOutputError,
    RefusalError,
    RetryableError,
    error_for_status,
    parse_retry_after,
)
from themi.ai.provider import DEFAULT_MAX_TOKENS, IMAGE_SIZE, Capabilities
from themi.ai.types import (
    CallKind,
    ChatResponse,
    Embeddings,
    ImageBlock,
    ImageResult,
    Message,
    StructuredResponse,
    ToolSpec,
    Transcription,
)
from themi.http import tls
from themi.storage.secrets import Secret

API_URL = "https://api.cloudflare.com/client/v4/accounts"
DEFAULT_IMAGE_MODEL = CLOUDFLARE_DEFAULT_IMAGE_MODEL
STEPS = 4  # the model's default; up to 8 costs more neurons for a little more detail
MAX_PROMPT = 2048


def account_url(address: str) -> str:
    """The `.../accounts/<id>/ai` base from an account ID or a URL that holds one."""
    address = address.strip().rstrip("/")
    if not address:
        raise ValueError("Cloudflare needs the account ID in the backend's address")
    if address.startswith("https://"):
        return address if address.endswith("/ai") else f"{address}/ai"
    return f"{API_URL}/{address}/ai"


class CloudflareProvider:
    name = "cloudflare"

    def __init__(
        self,
        api_token: Secret,
        address: str,
        model: str = DEFAULT_IMAGE_MODEL,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # A display name ("FLUX.1 schnell") isn't a route: Cloudflare answers 400 "No route for
        # that URI" (bug 2026-11-07). Only a Workers AI model ID is used as given.
        self.model = model if model.startswith(("@cf/", "@hf/")) else DEFAULT_IMAGE_MODEL
        self.capabilities = Capabilities(tools=False, structured=False, audio=False)
        self._base = account_url(address)
        self._token = api_token
        self._http = httpx.AsyncClient(verify=tls(), transport=transport, timeout=timeout)

    async def image(
        self, prompt: str, size: str = IMAGE_SIZE, *, kind: CallKind = CallKind.BACKGROUND
    ) -> ImageResult:
        """FLUX.1 [schnell] makes square 1024px pictures; `size` isn't asked for."""
        headers = {"Authorization": f"Bearer {self._token.reveal()}"}
        body = {"prompt": prompt[:MAX_PROMPT], "steps": STEPS}
        try:
            response = await self._http.post(
                f"{self._base}/run/{self.model}", headers=headers, json=body
            )
        except httpx.TimeoutException as exc:
            raise RetryableError("cloudflare request timed out") from exc
        except httpx.HTTPError as exc:
            raise RetryableError(f"couldn't reach cloudflare ({type(exc).__name__})") from exc
        data = _json(response)
        if response.status_code != 200 or data.get("success") is False:
            message = "; ".join(
                str(e.get("message", "")) for e in data.get("errors") or [] if isinstance(e, dict)
            )
            if response.status_code == 400 and "nsfw" in message.lower():
                raise RefusalError("Cloudflare declined this picture", category="safety")
            raise error_for_status(
                response.status_code if response.status_code != 200 else 502,
                f"cloudflare returned {response.status_code}: {message}".strip(),
                parse_retry_after(response.headers.get("retry-after")),
            )
        result = data.get("result", data)
        encoded = result.get("image") if isinstance(result, dict) else None
        if not encoded:
            raise MalformedOutputError("cloudflare sent no picture")
        try:
            picture = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise MalformedOutputError("cloudflare's picture wasn't base64") from exc
        return ImageResult(picture, _mime(picture), self.name, self.model)

    async def chat(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: CallKind = CallKind.INTERACTIVE,
    ) -> ChatResponse:
        raise CapabilityError("this Cloudflare backend only makes pictures")

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
        raise CapabilityError("this Cloudflare backend only makes pictures")

    async def transcribe(
        self, audio: bytes, mime_type: str, *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Transcription:
        raise CapabilityError("this Cloudflare backend only makes pictures")

    async def embed(
        self, texts: Sequence[str], *, kind: CallKind = CallKind.INTERACTIVE
    ) -> Embeddings:
        raise CapabilityError("this Cloudflare backend only makes pictures")


def _mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json() if response.content else {}
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
