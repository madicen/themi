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
from themi.ai.types import ImageReference, Message
from themi.storage.secrets import Cipher, Secret, generate_key

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
SEEN: list[httpx.Request] = []


SCHNELL = "@cf/black-forest-labs/flux-1-schnell"
KLEIN = "@cf/black-forest-labs/flux-2-klein-4b"
CHAMELEON = ImageReference(TINY_PNG, "image/png", "the chameleon")


def provider(*answers: httpx.Response, model: str = KLEIN) -> CloudflareProvider:
    """Answers each request with the next of `answers` (the last one again after that)."""
    queue = list(answers)

    def handle(request: httpx.Request) -> httpx.Response:
        SEEN.append(request)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return CloudflareProvider(
        Secret("cf-token"), "acct123", model, transport=httpx.MockTransport(handle)
    )


def form(request: httpx.Request) -> dict[str, bytes]:
    """A multipart request's fields, by name (files and plain fields alike)."""
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    fields: dict[str, bytes] = {}
    for part in request.content.split(b"--" + boundary):
        head, _, body = part.partition(b"\r\n\r\n")
        if b'name="' in head:
            name = head.split(b'name="')[1].split(b'"')[0].decode()
            fields[name] = body.removesuffix(b"\r\n")
    return fields


def ok(data: bytes) -> httpx.Response:
    image = base64.b64encode(data).decode()
    return httpx.Response(200, json={"result": {"image": image}, "success": True, "errors": []})


async def test_a_picture_from_flux_schnell_is_asked_in_json() -> None:
    SEEN.clear()
    picture = await provider(ok(JPEG), model=SCHNELL).image(
        "a broom by a door", references=[CHAMELEON]
    )
    assert (picture.data, picture.mime_type, picture.provider) == (JPEG, "image/jpeg", "cloudflare")
    (request,) = SEEN
    assert str(request.url) == (
        "https://api.cloudflare.com/client/v4/accounts/acct123/ai/run/"
        "@cf/black-forest-labs/flux-1-schnell"
    )
    assert request.headers["authorization"] == "Bearer cf-token"
    assert json.loads(request.content) == {"prompt": "a broom by a door", "steps": 4}
    assert picture.model == SCHNELL  # schnell can't take the reference; it's left out


async def test_flux_2_klein_is_the_default_and_takes_a_multipart_form() -> None:
    """BD4c: klein draws clearer pictures for free, and keeps to the chameleon sent as
    `input_image_0`, so every step picture shows the same Themi."""
    SEEN.clear()
    picture = await provider(ok(JPEG)).image("a broom by a door", references=[CHAMELEON])
    assert (picture.data, picture.model) == (JPEG, KLEIN)
    (request,) = SEEN
    assert request.url.path.endswith("/ai/run/@cf/black-forest-labs/flux-2-klein-4b")
    assert request.headers["content-type"].startswith("multipart/form-data")
    fields = form(request)
    # BD4d: the reference shows only the look, so the model poses it anew for the step
    assert fields["prompt"] == (
        b"Image 0 only shows what the chameleon looks like: draw it in a new scene and a new "
        b"pose, keeping its face, colours and markings. a broom by a door"
    )
    assert b"exactly" not in fields["prompt"]
    assert (fields["width"], fields["height"]) == (b"1024", b"1024")
    assert fields["input_image_0"] == TINY_PNG
    assert b'filename="image0.png"' in request.content


async def test_klein_without_a_reference_is_still_a_form() -> None:
    SEEN.clear()
    await provider(ok(JPEG)).image("a mop", "768x512")
    fields = form(SEEN[-1])
    assert fields == {"prompt": b"a mop", "width": b"768", "height": b"512"}


async def test_klein_turning_a_request_down_falls_back_to_schnell() -> None:
    """If Cloudflare changes klein's form (its schema wasn't published when this was
    built), pictures keep coming from schnell instead of stopping."""
    SEEN.clear()
    refused = httpx.Response(400, json={"success": False, "errors": [{"message": "bad input"}]})
    picture = await provider(refused, ok(JPEG)).image("a mop", references=[CHAMELEON])
    assert picture.model == SCHNELL
    assert [r.url.path.rsplit("/run/", 1)[1] for r in SEEN] == [KLEIN, SCHNELL]
    assert json.loads(SEEN[-1].content) == {"prompt": "a mop", "steps": 4}


async def test_no_fallback_for_a_refusal_an_outage_or_a_bad_token() -> None:
    for answer, error in [
        (
            httpx.Response(
                400, json={"success": False, "errors": [{"message": "Input flagged as NSFW"}]}
            ),
            RefusalError,
        ),
        (httpx.Response(503), RetryableError),
        (
            httpx.Response(
                401, json={"success": False, "errors": [{"message": "Authentication error"}]}
            ),
            PermanentError,
        ),
    ]:
        SEEN.clear()
        with pytest.raises(error):
            await provider(answer, ok(JPEG)).image("x")
        assert len(SEEN) == 1


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
    assert built.model == KLEIN
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
    assert entry.config.resolved_model == KLEIN
    assert isinstance(build_provider(entry.config), CloudflareProvider)


async def test_a_display_name_for_the_model_still_reaches_flux() -> None:
    """Bug (2026-11-07, the Pi): the backend's model was saved as "FLUX.1 schnell", which
    Cloudflare answers with 400 "No route for that URI". Anything that isn't a Workers AI
    model ID (`@cf/...`, `@hf/...`) runs the default model."""
    SEEN.clear()
    named = CloudflareProvider(
        Secret("cf-token"), "acct123", "FLUX.1 schnell",
        transport=httpx.MockTransport(lambda request: SEEN.append(request) or ok(JPEG)),
    )  # fmt: skip
    assert named.model == KLEIN  # the default (BD4c; schnell when this was found)
    await named.image("x")
    assert SEEN[-1].url.path.endswith("/ai/run/@cf/black-forest-labs/flux-2-klein-4b")
    other = CloudflareProvider(
        Secret("t"), "acct123", "@cf/stabilityai/stable-diffusion-xl-base-1.0"
    )
    assert other.model == "@cf/stabilityai/stable-diffusion-xl-base-1.0"  # a real ID is kept
