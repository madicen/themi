"""CR20b: Telegram is a channel module, and the website's chat is another. A member can use
only the site; one on both gets Themi's answer where they asked."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import httpx

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import csrf_of, web_client
from tests.scenarios.harness import ModelBank, Scenario
from themi.accounts import SYSTEM, Member, Role
from themi.ai.settings import AITask, RouteEntry
from themi.app import App, build_app, family_modules
from themi.standard.web_chat import WebChatChannel, WebChatModule
from themi.web.auth import WebAuth


def scripted(app: App, member: Member, models: ModelBank) -> None:
    backend = app.ai_settings.add_backend(member, member.id, "Primary", "ollama", model="primary")
    for task in AITask:
        app.ai_settings.set_chain(member, member.id, task, [RouteEntry(backend.id)])


async def signed_in(client: httpx.AsyncClient, app: App, member: Member) -> str:
    token = WebAuth(app.store).create_link_token(member)
    assert (await client.post(f"/login/{token}")).status_code == 303
    return csrf_of((await client.get("/")).text)


def said(page: str) -> list[str]:
    return [re.sub(r"\s+", " ", t).strip() for t in re.findall(r"<p>(.*?)</p>", page, re.S)]


async def test_a_member_who_uses_only_the_website(family: SeededFamily) -> None:
    """No Telegram at all: the chat page is the only way in, and the way back."""
    models = ModelBank()
    modules = [m for m in family_modules() if m.name != "telegram"] + [WebChatModule()]
    app = build_app(family.db, family.store.cipher, None, provider_factory=models, modules=modules)
    assert list(app.channel.channels) == ["web_chat"]
    guest = family.store.create_member(SYSTEM, "Guest", Role.MEMBER)
    scripted(app, guest, models)
    models["primary"].queue_text("Hello, Guest. I'm here on the website too.")
    async with web_client(SimpleNamespace(app=app)) as site:  # type: ignore[arg-type]
        csrf = await signed_in(site, app, guest)
        assert "Nothing yet" in (await site.get("/chat")).text
        assert app.store.get_member(guest.id).channels == ("web_chat",)
        response = await site.post("/chat", data={"csrf": csrf, "text": "Hi Themi"})
        assert response.status_code == 303
        await app.outbox.flush()
        page = (await site.get("/chat")).text
    assert said(page)[-2:] == ["Hi Themi", "Hello, Guest. I&#39;m here on the website too."]


async def test_buttons_are_buttons_and_a_tap_goes_to_its_handler(family: SeededFamily) -> None:
    modules = [m for m in family_modules() if m.name != "telegram"] + [WebChatModule()]
    app = build_app(family.db, family.store.cipher, None, provider_factory=ModelBank(),
                    modules=modules)  # fmt: skip
    taps: list[Any] = []

    async def on_tap(event: Any) -> None:
        taps.append(event.button)

    app.services.button_handlers["cr20b"] = on_tap
    from themi.channels.events import Button

    chat = app.services.get(WebChatChannel)
    erin = chat.join(family.erin)
    sent = await app.channel.send_text(erin, "Pick one", [Button("Yes", "cr20b", {"n": 1})])
    async with web_client(SimpleNamespace(app=app)) as site:  # type: ignore[arg-type]
        csrf = await signed_in(site, app, erin)
        page = (await site.get("/chat")).text
        assert f'action="/chat/{sent}/0"' in page and ">Yes</button>" in page
        await site.post(f"/chat/{sent}/0", data={"csrf": csrf})
        missing = await site.post(f"/chat/{sent}/5", data={"csrf": csrf})
        assert missing.status_code == 303
    assert [(b.label, b.kind, b.payload) for b in taps] == [("Yes", "cr20b", {"n": 1})]


async def test_a_member_on_both_channels_is_answered_where_they_asked(
    family: SeededFamily, fake_telegram: FakeTelegram
) -> None:
    scenario = Scenario(family, fake_telegram, modules=[*family_modules(), WebChatModule()])
    app = scenario.app
    assert list(app.channel.channels) == ["telegram", "web_chat"]
    await scenario.start()
    try:
        erin = scenario.member("Erin")
        chat = app.services.get(WebChatChannel)
        chat.join(erin)
        assert app.store.get_member(erin.id).channels == ("telegram", "web_chat")
        scenario.primary.queue_text("Answered on the website.")
        await chat.receive(erin, "Hello from the site")
        await app.outbox.flush()
        web = [m.text for m in chat.messages(erin)]
        assert web == ["Hello from the site", "Answered on the website."]
        assert "Answered on the website." not in scenario.inbox("Erin")
        scenario.primary.queue_text("Answered in Telegram.")
        await scenario.say("Erin", "And now from Telegram")
        assert "Answered in Telegram." in scenario.inbox("Erin")
        assert "Answered in Telegram." not in [m.text for m in chat.messages(erin)]
    finally:
        await scenario.stop()
