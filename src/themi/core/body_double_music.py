"""Music for body double sessions (BD5a: the built-in loops).

A few original loops ship with Themi (`web/static/audio/`, CC0, see LICENCES.md). Each
person has a chosen loop and volume, kept on their row; the session page plays it only
when they tap play (browsers block anything else anyway). "Play rain" in chat sets the
choice for the page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from themi.accounts import Member
from themi.core.tools import ToolContext, ToolFailed, tool


@dataclass(frozen=True)
class Loop:
    key: str
    name: str
    file: str  # under web/static/audio/


LOOPS = {
    loop.key: loop
    for loop in (
        Loop("lofi", "Lofi", "lofi.m4a"),
        Loop("rain", "Rain", "rain.m4a"),
        Loop("soft_piano", "Soft piano", "soft-piano.m4a"),
        Loop("brown_noise", "Brown noise", "brown-noise.m4a"),
    )
}
ALIASES = {
    "lofi": "lofi", "lo-fi": "lofi", "lo fi": "lofi", "beats": "lofi",
    "rain": "rain", "rain sounds": "rain",
    "piano": "soft_piano", "soft piano": "soft_piano", "soft_piano": "soft_piano",
    "brown noise": "brown_noise", "brown_noise": "brown_noise", "noise": "brown_noise",
}  # fmt: skip


def loop_for(said: str) -> Loop | None:
    key = ALIASES.get(" ".join(said.lower().replace("the ", "").split()))
    return LOOPS.get(key) if key else None


def set_sound(
    store: Any, member: Member, sound: str | None = None, volume: int | None = None
) -> None:
    store.update_settings(member, member.id, body_double_sound=sound, body_double_volume=volume)


@tool(
    "choose_session_sound",
    "Choose the built-in sound for their session page when they ask ('play rain', 'lofi "
    "please', 'brown noise'): lofi, rain, soft piano or brown noise. It plays on the "
    "session page once they tap play there. sound: the one they named.",
    {"sound": {"type": "string", "enum": ["lofi", "rain", "soft piano", "brown noise"]}},
)
async def choose_session_sound(ctx: ToolContext, args: dict[str, Any]) -> str:
    loop = loop_for(str(args.get("sound", "")))
    if loop is None:
        raise ToolFailed("The built-in sounds are lofi, rain, soft piano and brown noise.")
    set_sound(ctx.services.store, ctx.member, loop.key)
    return f"Set: {loop.name} on the session page; it plays once they tap play there."
