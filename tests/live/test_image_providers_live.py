"""BD4a: smoke tests for picture-making against real providers. Opt-in: `make test-live`.

Each costs a few cents (neither has a free tier for pictures), and is skipped unless its
key is set:
- THEMI_LIVE_GEMINI_IMAGE_KEY   a Gemini key with billing on (gemini-3.1-flash-lite-image)
- THEMI_LIVE_OPENAI_IMAGE_KEY   an OpenAI key (gpt-image-2, low quality)

Use test accounts, never the family's real keys.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from themi.ai import CallKind, call_with_retry
from themi.ai.adapters import AdapterConfig, AdapterKind, build_provider
from themi.ai.adapters.defaults import GEMINI_DEFAULT_IMAGE_MODEL, OPENAI_DEFAULT_IMAGE_MODEL
from themi.storage.secrets import Secret
from themi_home.step_images import image_prompt


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
async def test_a_cloudflare_step_picture() -> None:
    """Free within the daily allowance (about 58 neurons of 10,000)."""
    provider = build_provider(
        AdapterConfig(
            "cloudflare",
            api_key=Secret(os.environ["THEMI_LIVE_CLOUDFLARE_TOKEN"]),
            base_url=os.environ["THEMI_LIVE_CLOUDFLARE_ACCOUNT"],
        )
    )
    picture = await call_with_retry(
        lambda: provider.image(image_prompt("Fold the towels into thirds")), CallKind.BACKGROUND
    )
    assert picture.mime_type.startswith("image/") and len(picture.data) > 1000
