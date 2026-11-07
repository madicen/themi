"""Cloudflare Workers AI for step pictures: the request, the answer, its errors, and the
router moving past it for anything that isn't a picture."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from tests.fakes.scripted_provider import TINY_PNG
from tests.fixtures.family import SeededFamily
from themi.ai.adapters import AdapterConfig, build_provider
from themi.ai.adapters.cloudflare import CloudflareProvider, account_url
from themi.ai.errors import (
    CapabilityError,
    MalformedOutputError,
    PermanentError,
    RefusalError,
    RetryableError,
)
from themi.ai.settings import AISettingsStore, AITask, RouteEntry
from themi.ai.types import Message
from themi.storage.secrets import Cipher, Secret, generate_key

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
SEEN: list[httpx.Request] = []


def provider(answer: httpx.Response) -> CloudflareProvider:
    def handle(request: httpx.Request) -> httpx.Response:
        SEEN.append(request)
        return answer

    return CloudflareProvider(Secret("cf-token"), "acct123", transport=httpx.MockTransport(handle))


def ok(data: bytes) -> httpx.Response:
    image = base64.b64encode(data).decode()
    return httpx.Response(200, json={"result": {"image": image}, "success": True, "errors": []})


async def test_a_picture_from_flux() -> None:
    SEEN.clear()
    picture = await provider(ok(JPEG)).image("a broom by a door")
    assert (picture.data, picture.mime_type, picture.provider) == (JPEG, "image/jpeg", "cloudflare")
    (request,) = SEEN
    assert str(request.url) == (
        "https://api.cloudflare.com/client/v4/accounts/acct123/ai/run/"
        "@cf/black-forest-labs/flux-1-schnell"
    )
    assert request.headers["authorization"] == "Bearer cf-token"
    assert json.loads(request.content) == {"prompt": "a broom by a door", "steps": 4}


async def test_png_answers_are_labelled_png() -> None:
    assert (await provider(ok(TINY_PNG)).image("x")).mime_type == "image/png"


async def test_errors_map_to_the_routers_kinds() -> None:
    with pytest.raises(RetryableError):
        await provider(httpx.Response(429, headers={"retry-after": "5"})).image("x")
    with pytest.raises(RetryableError):
        await provider(httpx.Response(503)).image("x")
    with pytest.raises(PermanentError):
        await provider(httpx.Response(401, json={"success": False, "errors": [
            {"message": "Authentication error"}]})).image("x")  # fmt: skip
    with pytest.raises(RefusalError):
        await provider(httpx.Response(400, json={"success": False, "errors": [
            {"message": "Input flagged as NSFW"}]})).image("x")  # fmt: skip
    with pytest.raises(MalformedOutputError):
        await provider(httpx.Response(200, json={"result": {}, "success": True})).image("x")


async def test_only_pictures() -> None:
    with pytest.raises(CapabilityError):
        await provider(ok(JPEG)).chat("s", [Message.user("hi")])
    with pytest.raises(CapabilityError):
        await provider(ok(JPEG)).structured("s", "p", {})


def test_the_address_is_the_account_id_or_a_url() -> None:
    assert account_url("abc") == "https://api.cloudflare.com/client/v4/accounts/abc/ai"
    url = "https://api.cloudflare.com/client/v4/accounts/abc/ai"
    assert account_url(url) == url and account_url(url[:-3]) == url
    with pytest.raises(ValueError):
        account_url("  ")


def test_built_from_a_backend() -> None:
    built = build_provider(AdapterConfig("cloudflare", api_key=Secret("t"), base_url="abc"))
    assert isinstance(built, CloudflareProvider)
    assert built.model == "@cf/black-forest-labs/flux-1-schnell"
    with pytest.raises(PermanentError):
        build_provider(AdapterConfig("cloudflare", api_key=Secret("t")))  # no account ID


def test_a_cloudflare_backend_can_lead_the_step_picture_route(family: SeededFamily) -> None:
    ai = AISettingsStore(family.db, Cipher(generate_key()))
    erin = family.erin
    cloudflare = ai.add_backend(erin, erin.id, "Cloudflare", "cloudflare",
                                base_url="acct123", api_key=Secret("cf-token"))  # fmt: skip
    ai.set_chain(erin, erin.id, AITask.STEP_IMAGE, [RouteEntry(cloudflare.id)])
    (entry,) = ai.resolve(erin.id, AITask.STEP_IMAGE)
    assert entry.config.kind == "cloudflare"
    assert entry.config.resolved_model == "@cf/black-forest-labs/flux-1-schnell"
    assert isinstance(build_provider(entry.config), CloudflareProvider)
