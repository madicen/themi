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


# ----- BD5c: music that suits the task -------------------------------------------------------

# With nothing learned yet: a default per kind of job. None of the built-ins is fast (they're
# kept slow, 60-90 BPM), so tidying gets lofi too, the one with a beat.
DEFAULTS = {"deep_work": "builtin:lofi", "tidy": "builtin:lofi"}
LEARNED_AFTER = 2  # finished sessions with the same music in the cell before it's offered
OFFER_LEARNED_TEXT = "{name} again, like last time?"
OFFER_DEFAULT_TEXT = "Some {name} while you work?"


@dataclass(frozen=True)
class Pick:
    music: str  # "builtin:rain" or a Spotify uri
    name: str
    learned: bool


def pick(rows: list[dict[str, Any]], category: str | None, part: str) -> Pick | None:
    """What to offer for this kind of job at this part of the day: the music that played
    most in their finished sessions there (at least LEARNED_AFTER times; the latest wins a
    tie), else the kind's default, else nothing. Pure, over the session rows."""
    from themi.core.body_double_modes import part_of_day

    counts: dict[str, tuple[int, int, str]] = {}  # music -> (times, latest id, name)
    for row in rows:
        if (
            row.get("outcome") != "finished"
            or not row.get("music")
            or row.get("category") != category
            or part_of_day(row["hour_of_week"]) != part
        ):
            continue
        times, _, _ = counts.get(row["music"], (0, 0, ""))
        counts[row["music"]] = (times + 1, row["id"], row.get("music_name") or "")
    ranked = sorted(counts.items(), key=lambda kv: (kv[1][0], kv[1][1]), reverse=True)
    if ranked and ranked[0][1][0] >= LEARNED_AFTER:
        music, (_, _, name) = ranked[0]
        return Pick(music, name or music, True)
    default = DEFAULTS.get(category or "")
    if default is None:
        return None
    loop = LOOPS[default.removeprefix("builtin:")]
    return Pick(default, loop.name.lower(), False)


def offer_text(chosen: Pick) -> str:
    if chosen.learned:
        return OFFER_LEARNED_TEXT.format(name=chosen.name[:1].upper() + chosen.name[1:])
    return OFFER_DEFAULT_TEXT.format(name=chosen.name)


class MusicOffers:
    """Offers the music that suits the job once, at a session's start: [Play] [Not now].
    Never starts anything on its own, and never says how sessions went."""

    def __init__(self, services: Any, body_double: Any) -> None:
        self.services = services
        self.bd = body_double
        self.db = services.store.db

    def install(self) -> None:
        self.bd.start_decorators.append(self.offer)
        self.services.button_handlers["music_offer"] = self.on_button

    def choice(self, session: Any) -> Pick | None:
        from themi.core.body_double_modes import part_of_day

        rows = self.db.query(
            "SELECT * FROM body_double_sessions WHERE member_id = ? AND ended_at IS NOT NULL",
            (session.member_id,),
        )
        return pick(rows, session.category, part_of_day(session.row["hour_of_week"]))

    async def offer(self, session: Any, text: str, buttons: list[Any]) -> tuple[str, list[Any]]:
        from themi.channels.events import Button

        chosen = self.choice(session)
        if chosen is None:
            return text, buttons
        if not chosen.music.startswith("builtin:") and self.services.music is None:
            return text, buttons  # Spotify isn't set up any more
        tap = {"session": session.id, "music": chosen.music, "name": chosen.name, "text": text}
        return f"{text}\n{offer_text(chosen)}", [
            *buttons,
            Button("Play", "music_offer", {**tap, "action": "play"}),
            Button("Not now", "music_offer", {**tap, "action": "skip"}),
        ]

    async def on_button(self, event: Any) -> None:
        payload = event.button.payload
        member = self.services.store.get_member(event.member.id)
        said = str(payload.get("text", ""))
        if payload.get("action") != "play":
            result = said
        elif str(payload.get("music", "")).startswith("builtin:"):
            loop = LOOPS.get(str(payload["music"]).removeprefix("builtin:"))
            if loop is None:
                return
            set_sound(self.services.store, member, loop.key)
            result = f"{said}\n{loop.name} is ready on the session page: tap play there."
        else:
            result = f"{said}\n{await self._spotify(member, payload)}"
        if event.button.message_id is not None:
            await self.services.outbox.edit(member, event.button.message_id, result.strip())

    async def _spotify(self, member: Member, payload: dict[str, Any]) -> str:
        from themi.core.music import CATEGORY, PLAY

        outcome = await self.services.autonomy.stage(
            CATEGORY, member, f"Play {payload.get('name', '')} on Spotify",
            {"uri": payload["music"], "name": payload.get("name", "")}, PLAY,
            interactive=True, requested=True,
        )  # fmt: skip
        return outcome.message
