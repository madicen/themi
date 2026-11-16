"""BD4a: smoke tests for picture-making against real providers. Opt-in: `make test-live`.

Each costs a few cents (neither has a free tier for pictures), and is skipped unless its
key is set:
- THEMI_LIVE_GEMINI_IMAGE_KEY   a Gemini key with billing on (gemini-3.1-flash-lite-image)
- THEMI_LIVE_OPENAI_IMAGE_KEY   an OpenAI key (gpt-image-2, low quality)
- THEMI_LIVE_CLOUDFLARE_TOKEN and THEMI_LIVE_CLOUDFLARE_ACCOUNT   Cloudflare Workers AI
  (free within its daily allowance): FLUX.2 klein with the chameleon, and FLUX.1 schnell

Use test accounts, never the family's real keys.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from themi.ai import CallKind, call_with_retry
from themi.ai.adapters import AdapterConfig, AdapterKind, build_provider
from themi.ai.adapters.defaults import (
    CLOUDFLARE_DEFAULT_IMAGE_MODEL,
    CLOUDFLARE_FALLBACK_IMAGE_MODEL,
    GEMINI_DEFAULT_IMAGE_MODEL,
    OPENAI_DEFAULT_IMAGE_MODEL,
)
from themi.storage.secrets import Secret
from themi_home.step_images import chameleon_reference, image_prompt


def _providers() -> list[Any]:
    params = []

    def add(name: str, env: str, kind: AdapterKind, model: str, base_url: str | None) -> None:
        value = os.environ.get(env)
        marks = [] if value else [pytest.mark.skip(reason=f"set {env} to run")]
        make = lambda: build_provider(  # noqa: E731
            AdapterConfig(kind, api_key=Secret(os.environ[env]), model=model, base_url=base_url)
        )
        params.append(pytest.param(make, id=name, marks=marks))

    add("gemini", "THEMI_LIVE_GEMINI_IMAGE_KEY", "gemini", GEMINI_DEFAULT_IMAGE_MODEL, None)
    add("openai", "THEMI_LIVE_OPENAI_IMAGE_KEY", "openai_compat", OPENAI_DEFAULT_IMAGE_MODEL,
        "https://api.openai.com/v1")  # fmt: skip
    return params


@pytest.mark.parametrize("make", _providers())
async def test_a_step_picture(make: Any) -> None:
    provider = make()
    picture = await call_with_retry(
        lambda: provider.image(image_prompt("Load the plates into the dishwasher")),
        CallKind.BACKGROUND,
    )
    assert picture.mime_type.startswith("image/")
    assert len(picture.data) > 1000


@pytest.mark.skipif(
    not (
        os.environ.get("THEMI_LIVE_CLOUDFLARE_TOKEN")
        and os.environ.get("THEMI_LIVE_CLOUDFLARE_ACCOUNT")
    ),
    reason="set THEMI_LIVE_CLOUDFLARE_TOKEN and THEMI_LIVE_CLOUDFLARE_ACCOUNT to run",
)
@pytest.mark.parametrize("model", [CLOUDFLARE_DEFAULT_IMAGE_MODEL, CLOUDFLARE_FALLBACK_IMAGE_MODEL])
async def test_a_cloudflare_step_picture(model: str) -> None:
    """Free within the daily allowance (klein about 110 neurons with the chameleon, schnell
    about 58, of 10,000). Klein must answer itself, not by falling back to schnell (BD4c).
    THEMI_LIVE_PICTURE_DIR, when set, keeps the pictures there to look at."""
    provider = build_provider(
        AdapterConfig(
            "cloudflare",
            api_key=Secret(os.environ["THEMI_LIVE_CLOUDFLARE_TOKEN"]),
            base_url=os.environ["THEMI_LIVE_CLOUDFLARE_ACCOUNT"],
            model=model,
        )
    )
    reference = chameleon_reference()
    assert reference is not None
    picture = await call_with_retry(
        lambda: provider.image(image_prompt("Fold the towels into thirds"), references=[reference]),
        CallKind.BACKGROUND,
    )
    assert picture.mime_type.startswith("image/") and len(picture.data) > 1000
    assert picture.model == model
    folder = os.environ.get("THEMI_LIVE_PICTURE_DIR")
    if folder:
        name = model.rsplit("/", 1)[1]
        Path(folder, f"{name}.{picture.mime_type.split('/')[1]}").write_bytes(picture.data)
