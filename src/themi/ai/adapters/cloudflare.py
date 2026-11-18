"""Cloudflare Workers AI, for pictures only (BD4a's follow-up, 2026-11-06).

Its free tier is 10,000 "neurons" a day per account, with no card. The default model is
FLUX.2 [klein] 4B (BD4c): 26.05 neurons per 512x512 output tile and 5.37 per reference
tile (Cloudflare's pricing page, 2026-11-15), so a 1024x1024 picture with one small
reference is about 110 neurons, some 90 a day free. FLUX.1 [schnell] (4.8 a tile, 9.6 a
step: about 58 a picture at 4 steps) is the fallback.

    POST https://api.cloudflare.com/client/v4/accounts/<account id>/ai/run/<model>
    Authorization: Bearer <API token>
    FLUX.2: multipart form: prompt, width, height, input_image_0..3 (each under 512x512)
    FLUX.1 [schnell]: {"prompt": "...", "steps": 4}
    ->  {"result": {"image": "<base64 picture>"}, "success": true}

The backend's address is the account ID (or a full `.../accounts/<id>/ai` URL); its key is
an API token with the Workers AI permission. Chat, structured output, audio and
embeddings aren't offered here: the router moves on to the next backend.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from themi.ai.adapters.defaults import (
    CLOUDFLARE_DEFAULT_IMAGE_MODEL,
    CLOUDFLARE_FALLBACK_IMAGE_MODEL,
)
from themi.ai.errors import (
    CapabilityError,
    MalformedOutputError,
    PermanentError,
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
    ImageReference,
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
FALLBACK_IMAGE_MODEL = CLOUDFLARE_FALLBACK_IMAGE_MODEL
MULTIPART_PREFIX = "@cf/black-forest-labs/flux-2-"  # FLUX.2 models take a multipart form
STEPS = 4  # schnell's default; up to 8 costs more neurons for a little more detail
MAX_PROMPT = 2048
MAX_REFERENCES = 4  # input_image_0 to input_image_3
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}

log = logging.getLogger(__name__)


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
        self,
        prompt: str,
        size: str = IMAGE_SIZE,
        *,
        kind: CallKind = CallKind.BACKGROUND,
        references: Sequence[ImageReference] = (),
    ) -> ImageResult:
        """A picture from the backend's model. FLUX.2 models take a multipart form, with
        `references` as `input_image_N`; FLUX.1 [schnell] takes JSON and ignores them.
        When a FLUX.2 model turns the request down (a 400 or 404 that isn't a safety
        refusal), FLUX.1 [schnell] is asked once instead, so pictures keep coming."""
        if not self.model.startswith(MULTIPART_PREFIX):
            return await self._run(self.model, json={"prompt": prompt[:MAX_PROMPT], "steps": STEPS})
        try:
            return await self._run(self.model, files=_form(prompt, size, references))
        except PermanentError as exc:
            if exc.status not in (400, 404):
                raise
            log.warning("Cloudflare's %s turned a picture down (%s); trying %s", self.model,
                        exc, FALLBACK_IMAGE_MODEL)  # fmt: skip
            body = {"prompt": prompt[:MAX_PROMPT], "steps": STEPS}
            return await self._run(FALLBACK_IMAGE_MODEL, json=body)

    async def _run(
        self,
        model: str,
        *,
        json: dict[str, Any] | None = None,
        files: list[tuple[str, tuple[str | None, bytes | str, str | None]]] | None = None,
    ) -> ImageResult:
        headers = {"Authorization": f"Bearer {self._token.reveal()}"}
        try:
            response = await self._http.post(
                f"{self._base}/run/{model}", headers=headers, json=json, files=files
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
        return ImageResult(picture, _mime(picture), self.name, model)

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


def _form(
    prompt: str, size: str, references: Sequence[ImageReference]
) -> list[tuple[str, tuple[str | None, bytes | str, str | None]]]:
    """FLUX.2's multipart fields. Each reference goes as `input_image_N` (Cloudflare wants
    each under 512x512), and the prompt opens by saying it shows only the look ("image 0" is
    the first, as Cloudflare's examples count). Sent as files so the body is multipart even with no
    reference."""
    # BD4d (tried on the Pi, 2026-11-17): "exactly as in image 0" pasted the reference's pose
    # into the picture; saying the image shows only the look lets the model pose it anew.
    for i, ref in reversed(list(enumerate(references[:MAX_REFERENCES]))):
        prompt = (
            f"Image {i} only shows what {ref.subject} looks like: draw it in a new scene and a "
            f"new pose, keeping its face, colours and markings. {prompt}"
        )
    width, _, height = size.partition("x")
    fields: list[tuple[str, tuple[str | None, bytes | str, str | None]]] = [
        ("prompt", (None, prompt[:MAX_PROMPT], None)),
        ("width", (None, width or "1024", None)),
        ("height", (None, height or width or "1024", None)),
    ]
    for i, ref in enumerate(references[:MAX_REFERENCES]):
        name = f"image{i}{EXTENSIONS.get(ref.mime_type, '.png')}"
        fields.append((f"input_image_{i}", (name, ref.data, ref.mime_type)))
    return fields


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
