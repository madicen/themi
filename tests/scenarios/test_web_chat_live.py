"""WC1: the website chat does what the simulator showed. It updates itself, sends without
reloading, shows typing, marks edits, takes reactions both ways and replies to a message."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx

from tests.fixtures.family import SeededFamily
from tests.fixtures.web import csrf_of, web_client
from tests.scenarios.harness import ModelBank
from themi.accounts import Member
from themi.app import App, build_app, family_modules
from themi.autonomy import ExecutionContext
from themi.channels.base import Channel
from themi.channels.events import InboundEvent
from themi.standard.web_chat import WebChatChannel, WebChatModule
from themi.web.auth import WebAuth

HTMX = {"HX-Request": "true"}


def web_only(family: SeededFamily) -> App:
    modules = [m for m in family_modules() if m.name != "telegram"] + [WebChatModule()]
    return build_app(family.db, family.store.cipher, None, provider_factory=ModelBank(),
                     modules=modules)  # fmt: skip


@asynccontextmanager
async def site_for(app: App, member: Member) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    async with web_client(SimpleNamespace(app=app)) as site:  # type: ignore[arg-type]
        token = WebAuth(app.store).create_link_token(member)
        assert (await site.post(f"/login/{token}")).status_code == 303
        yield site, csrf_of((await site.get("/")).text)


def version(page: str) -> str:
    found = re.search(r'data-version="([0-9a-f]+)"', page)
    assert found is not None
    return found.group(1)


class Held:
    """A handler that shows typing and waits until the test lets it answer."""

    def __init__(self, chat: WebChatChannel) -> None:
        self.chat = chat
        self.go = asyncio.Event()
        self.started = asyncio.Event()
        self.events: list[InboundEvent] = []

    async def handle(self, event: InboundEvent, channel: Channel) -> None:
        self.events.append(event)
        async with channel.typing(event.member):
            self.started.set()
            await self.go.wait()
        await channel.send_text(event.member, f"About {event.text!r}: done.")


async def test_sending_doesnt_wait_and_the_answer_comes_to_the_log(family: SeededFamily) -> None:
    app = web_only(family)
    chat = app.services.get(WebChatChannel)
    held = Held(chat)
    chat.handler = held
    async with site_for(app, family.erin) as (site, csrf):
        page = (await site.get("/chat")).text
        assert 'hx-get="/chat/log?v=' in page and "chat.js" in page
        sent = await site.post("/chat", data={"csrf": csrf, "text": "Hi"}, headers=HTMX)
        assert sent.status_code == 200  # the log, not a redirect, while the agent still works
        assert "<p>Hi</p>" in sent.text and 'id="chat-log"' in sent.text
        await held.started.wait()
        typing = await site.get(f"/chat/log?v={version(sent.text)}")
        assert typing.status_code == 200 and "Themi is typing…" in typing.text
        held.go.set()
        await chat.settle()
        after = await site.get(f"/chat/log?v={version(typing.text)}")
    assert "About &#39;Hi&#39;: done." in after.text
    assert "Themi is typing…" not in after.text


async def test_an_unchanged_log_is_204_until_something_changes(family: SeededFamily) -> None:
    app = web_only(family)
    chat = app.services.get(WebChatChannel)
    erin = chat.join(family.erin)
    sent = await chat.send_text(erin, "First")
    async with site_for(app, erin) as (site, _):
        first = await site.get("/chat/log")
        again = await site.get(f"/chat/log?v={version(first.text)}")
        assert again.status_code == 204
        await chat.edit_text(erin, sent, "First, changed")
        edited = await site.get(f"/chat/log?v={version(first.text)}")
    assert edited.status_code == 200
    assert "First, changed" in edited.text and '"chat-edited">edited<' in edited.text


async def test_a_check_reaction_on_the_site_approves_the_card(family: SeededFamily) -> None:
    app = web_only(family)
    chat = app.services.get(WebChatChannel)
    erin = chat.join(family.erin)
    archived: list[dict[str, Any]] = []

    async def archive(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        archived.append(payload)
        return "Archived 3 promos."

    app.services.autonomy.executors.register("gmail.archive")(archive)
    await app.services.autonomy.stage(
        "email_archive_noise", erin, "Archive 3 promo emails", {"count": 3}, "gmail.archive"
    )
    await app.outbox.flush()
    (card,) = [m for m in chat.messages(erin) if m.direction == "out"]
    async with site_for(app, erin) as (site, csrf):
        page = (await site.get("/chat")).text
        assert f'action="/chat/{card.id}/react"' in page and 'value="✅"' in page
        answer = await site.post(
            f"/chat/{card.id}/react", data={"csrf": csrf, "emoji": "✅"}, headers=HTMX
        )
    assert answer.status_code == 200
    assert archived == [{"count": 3}]
    (shown,) = [m for m in chat.messages(erin) if m.id == card.id]
    assert shown.reactions == ("✅",)
    assert shown.text.endswith("Done. Archived 3 promos.") and shown.edited


async def test_the_same_reaction_again_takes_it_off_without_an_event(family: SeededFamily) -> None:
    app = web_only(family)
    chat = app.services.get(WebChatChannel)
    events: list[InboundEvent] = []

    class Record:
        async def handle(self, event: InboundEvent, channel: Channel) -> None:
            events.append(event)

    chat.handler = Record()
    erin = chat.join(family.erin)
    sent = await chat.send_text(erin, "A reply")
    assert await chat.react_as(erin, sent, "👎")
    assert await chat.react_as(erin, sent, "👍")
    assert await chat.react_as(erin, sent, "👍")
    assert not await chat.react_as(erin, sent, "🦄")  # not one the page offers
    assert [(e.kind, e.reaction.added if e.reaction else None) for e in events] == [
        ("reaction", ("👎",)),
        ("reaction", ("👍",)),
    ]
    assert chat.messages(erin)[-1].reactions == ()


async def test_themis_own_reaction_shows_on_their_message(family: SeededFamily) -> None:
    app = web_only(family)
    chat = app.services.get(WebChatChannel)
    erin = chat.join(family.erin)
    await chat.receive(erin, "Can you look at this?")
    mine = chat.messages(erin)[0]
    await app.channel.react(erin, mine.id, "👀")
    async with site_for(app, erin) as (site, _):
        page = (await site.get("/chat")).text
    assert chat.messages(erin)[0].reactions == ("👀",)  # theirs, not Themi's answer
    assert re.search(r'class="chat-reacted"[^>]*>👀<', page)


async def test_a_reply_carries_what_it_answers(family: SeededFamily) -> None:
    app = web_only(family)
    chat = app.services.get(WebChatChannel)
    events: list[InboundEvent] = []

    class Record:
        async def handle(self, event: InboundEvent, channel: Channel) -> None:
            events.append(event)

    chat.handler = Record()
    erin = chat.join(family.erin)
    answered = await chat.send_text(erin, "Your dentist is on Tuesday at 3")
    async with site_for(app, erin) as (site, csrf):
        replying = (await site.get(f"/chat?reply={answered}")).text
        assert f'name="reply_to" value="{answered}"' in replying
        assert "Your dentist is on Tuesday at 3" in replying.split('class="chat-replying"')[1]
        await site.post("/chat", data={"csrf": csrf, "text": "/bug wrong day",
                                       "reply_to": str(answered)})  # fmt: skip
        page = (await site.get("/chat")).text
    assert events[-1].reply_to_message_id == answered
    assert chat.messages(erin)[-1].quote == "Your dentist is on Tuesday at 3"
    assert '<blockquote class="chat-quote">Your dentist is on Tuesday at 3</blockquote>' in page


async def test_someone_elses_messages_cant_be_reacted_to_or_replied_to(
    family: SeededFamily,
) -> None:
    app = web_only(family)
    chat = app.services.get(WebChatChannel)
    events: list[InboundEvent] = []

    class Record:
        async def handle(self, event: InboundEvent, channel: Channel) -> None:
            events.append(event)

    chat.handler = Record()
    erin = chat.join(family.erin)
    other = chat.join(family.husband)
    theirs = await chat.send_text(other, "His own message")
    assert not await chat.react_as(erin, theirs, "👍")
    await chat.receive(erin, "Replying to it anyway", theirs)
    assert events[-1].reply_to_message_id is None
    assert chat.messages(erin)[-1].quote == ""
    async with site_for(app, erin) as (site, csrf):
        refused = await site.post(
            f"/chat/{theirs}/react", data={"csrf": csrf, "emoji": "👍"}, headers=HTMX
        )
        replying = (await site.get(f"/chat?reply={theirs}")).text
    assert "That message isn&#39;t there any more." in refused.text
    assert "His own message" not in replying
    assert [m.reactions for m in chat.messages(other)] == [()]


async def test_the_log_needs_a_session(family: SeededFamily) -> None:
    app = web_only(family)
    async with web_client(SimpleNamespace(app=app)) as site:  # type: ignore[arg-type]
        response = await site.get("/chat/log")
    assert response.status_code in (302, 303, 401)
