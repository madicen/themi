"""Everyday chat commands: /pause, /resume, /tracking, /site, /link and /help.

Each has a plain-language equivalent too: the model can pause and resume
messages through tools, so "no meal reminders today please" works as well
as /pause meals today.
"""

from __future__ import annotations

from typing import Any

from themi import clock
from themi.accounts import TRACKING_INPUTS, Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.channels.pauses import (
    EVERYTHING,
    TOPIC_WORDS,
    TOPICS,
    PauseBook,
    PauseError,
    normalise_topic,
    parse_until,
)
from themi.core.services import Services
from themi.core.tools import ToolContext, tool
from themi.localtime import to_local
from themi.web.auth import WebAuth

TRACKING_WORDS = {
    "text_notes": "Notes about how you're doing, when you mention it",
    "message_timing": "When you tend to reply, and how quickly",
    "device_activity": "Activity from household devices (laundry, feeders)",
}
TRACKING_SHORT = {
    "text_notes": "energy notes",
    "message_timing": "reply timing",
    "device_activity": "device activity",
}
PAUSE_HELP = (
    "To pause something, send for example /pause meals today, /pause laundry 3 hours or "
    "/pause everything tonight. Topics: {topics}. Replies and urgent alerts always come "
    "through."
)
LINK_SOON = "Linking Gmail arrives with the email features, soon. Nothing to set up yet."


def _when(services: Services, moment: Any) -> str:
    family = services.store.get_family()
    local = to_local(moment, family.timezone if family else "UTC")
    today = to_local(clock.now(), family.timezone if family else "UTC").date()
    day = "" if local.date() == today else local.strftime(" on %A")
    return local.strftime("%I:%M %p").lstrip("0") + day


def tracking_message(member: Member) -> tuple[str, list[Button]]:
    lines = ["Here's what Themi notices about you. Only you see this."]
    buttons = []
    for name in TRACKING_INPUTS:
        on = member.tracks(name)
        lines.append(f"• {TRACKING_WORDS[name]}: {'on' if on else 'off'}")
        verb = "Stop" if on else "Start"
        buttons.append(
            Button(f"{verb} {TRACKING_SHORT[name]}", "tracking", {"input": name, "on": not on})
        )
    return "\n".join(lines), buttons


class Commands:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.pauses = services.outbox.pauses

    def install(self) -> None:
        s = self.services
        s.add_command("/pause", self.on_pause, "Hold a kind of message for a while")
        s.add_command("/resume", self.on_resume, "Bring paused messages back")
        s.add_command("/tracking", self.on_tracking, "See and change what Themi notices about you")
        s.add_command("/site", self.on_site, "Get a sign-in link for the website")
        s.add_command("/link", self.on_link, "Connect an account, such as Gmail")
        s.add_command("/help", self.on_help, "What you can ask for")
        s.button_handlers["tracking"] = self.on_tracking_button
        s.tools.register(pause_messages)
        s.tools.register(resume_messages)

    async def _reply(self, member: Member, text: str, **kwargs: Any) -> None:
        await self.services.outbox.send(member, text, priority=Priority.REPLY, **kwargs)

    # ----- /pause and /resume -----------------------------------------------------

    def pause(self, member: Member, topic: str, duration: str) -> str:
        family = self.services.store.get_family()
        until = parse_until(duration, member, family.timezone if family else "UTC", clock.now())
        pause = self.pauses.pause(member, topic, until)
        return (
            f"Okay, holding {TOPIC_WORDS[pause.topic]} until {_when(self.services, until)}. "
            "/resume brings them back sooner."
        )

    def resume(self, member: Member, topic: str | None) -> str:
        ended = self.pauses.resume(member, None if topic in (None, "", EVERYTHING) else topic)
        if not ended:
            return "Nothing was paused."
        self.services.outbox.release_held(member)  # flush re-checks quiet hours and limits
        return "Back to normal. Anything that was held will come through."

    async def on_pause(self, member: Member, argument: str) -> None:
        words = argument.split(maxsplit=1)
        if not words:
            active = self.pauses.active(member)
            parts = [PAUSE_HELP.format(topics=", ".join(sorted(TOPICS)))]
            if active:
                parts.append(
                    "Paused now:\n"
                    + "\n".join(
                        f"• {TOPIC_WORDS[p.topic]} until {_when(self.services, p.until)}"
                        for p in active
                    )
                )
            await self._reply(member, "\n\n".join(parts))
            return
        try:
            reply = self.pause(member, words[0], words[1] if len(words) > 1 else "")
        except PauseError as exc:
            reply = str(exc)
        await self._reply(member, reply)

    async def on_resume(self, member: Member, argument: str) -> None:
        try:
            reply = self.resume(member, argument.strip() or None)
        except PauseError as exc:
            reply = str(exc)
        await self._reply(member, reply)

    # ----- /tracking -----------------------------------------------------------------

    async def on_tracking(self, member: Member, argument: str) -> None:
        text, buttons = tracking_message(member)
        await self._reply(member, text, buttons=buttons, kind="tracking")

    async def on_tracking_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        name, on = str(event.button.payload["input"]), bool(event.button.payload["on"])
        if name not in TRACKING_INPUTS:
            return
        member = self.services.store.update_settings(
            event.member, event.member.id, tracking={name: on}
        )
        text, buttons = tracking_message(member)
        if event.button.message_id is not None:
            await self.services.outbox.edit(member, event.button.message_id, text, buttons)

    # ----- /site, /link, /help -------------------------------------------------------

    async def on_site(self, member: Member, argument: str) -> None:
        base = self.services.site_url
        if not base:
            await self._reply(member, "The website address isn't set up yet.")
            return
        token = WebAuth(self.services.store).create_link_token(member)
        await self._reply(
            member,
            "Here's a sign-in link for the Themi website. It works once, within 10 minutes:\n"
            f"{base}/login/{token}",
            kind="system",
            link_preview=False,  # a preview fetch would otherwise reach the link first
        )

    async def on_link(self, member: Member, argument: str) -> None:
        await self._reply(member, LINK_SOON)

    async def on_help(self, member: Member, argument: str) -> None:
        lines = ["You can just talk to Themi. A few shortcuts, too:"]
        lines += [f"{name} · {words}" for name, words in self.services.command_help.items()]
        await self._reply(member, "\n".join(lines))


@tool(
    "pause_messages",
    "Hold a kind of message Themi starts (meal reminders, laundry nudges...) for a while, when "
    "the person asks for a break from them. Replies and urgent alerts are never held.",
    {
        "topic": {"type": "string", "enum": sorted(TOPICS)},
        "duration": {
            "type": "string",
            "description": "'today', 'tonight', 'tomorrow', or an amount like '3 hours', '2 days'.",
        },
    },
)
async def pause_messages(ctx: ToolContext, args: dict[str, Any]) -> str:
    commands = Commands(ctx.services)
    try:
        return commands.pause(ctx.member, args["topic"], args["duration"])
    except PauseError as exc:
        return f"Not paused: {exc}"


@tool(
    "resume_messages",
    "End a pause early when the person wants those messages back.",
    {"topic": {"type": "string", "enum": [*sorted(TOPICS), "all"]}},
)
async def resume_messages(ctx: ToolContext, args: dict[str, Any]) -> str:
    topic = args["topic"]
    try:
        return Commands(ctx.services).resume(
            ctx.member, None if topic == "all" else normalise_topic(topic)
        )
    except PauseError as exc:
        return str(exc)


__all__ = ["Commands", "PauseBook", "pause_messages", "resume_messages", "tracking_message"]
