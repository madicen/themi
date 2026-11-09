"""Music for body double sessions (BD5a: the built-in loops).

A few original loops ship with Themi (`web/static/audio/`, CC0, see LICENCES.md). Each
person has a chosen loop and volume, kept on their row; the session page plays it only
when they tap play (browsers block anything else anyway). "Play rain" in chat sets the
choice for the page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from themi.accounts import Member
from themi.core import keys
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.modules import Module, ModuleContext


@dataclass(frozen=True)
class Loop:
    key: str
    name: str
    file: str  # under themi_home/web/static/audio/ (CR17b)


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
    from themi_home.body_double import BodyDoublePreferences  # CR7a; a cycle at the top

    store.save_preferences(
        member,
        member.id,
        BodyDoublePreferences,
        body_double_sound=sound,
        body_double_volume=volume,
    )


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
DEFAULTS = {"deep_work": "builtin:lofi", "tidy": "builtin:lofi", "cooking": "builtin:lofi"}
LEARNED_AFTER = 2  # finished sessions with the same music in the cell before it's offered
OFFER_LEARNED_TEXT = "{name} again, like last time?"
OFFER_DEFAULT_TEXT = "Some {name} while you work?"
OFFER_MINE_TEXT = "Some {name} while you work, or one of yours?"  # F34i
OFFER_ONLY_MINE_TEXT = "Some of your music while you work?"
MORE_TEXT = "More of yours:"
SHOWN = 3  # their own playlists on the offer itself
PAGE = 10  # and on each page of "More"
# F34i: words in a playlist's name that suit a kind of job.
FITS = {
    "deep_work": ("focus", "study", "concentrat", "deep", "instrumental", "ambient", "work"),
    "admin": ("focus", "work", "instrumental", "ambient"),
    "chores": ("clean", "chore", "dance", "upbeat", "energy", "party", "pop", "kitchen"),
    "tidy": ("clean", "chore", "dance", "upbeat", "energy", "party", "pop", "kitchen"),
    "cooking": ("kitchen", "cook", "dinner", "dance", "upbeat", "jazz", "soul"),  # CK5
}


def ranked(playlists: list[dict[str, str]], category: str | None,
           last: str | None) -> list[dict[str, str]]:  # fmt: skip
    """F34i: the one from their last session of this kind first, then names that fit the
    job, then the rest as Spotify lists them (most recent first)."""
    fits = FITS.get(category or "", ())
    first = [p for p in playlists if p["uri"] == last]
    fitting = [p for p in playlists if p not in first and any(w in p["name"].lower()
                                                             for w in fits)]  # fmt: skip
    return [*first, *fitting, *(p for p in playlists if p not in first and p not in fitting)]


@dataclass(frozen=True)
class Pick:
    music: str  # "builtin:rain" or a Spotify uri
    name: str
    learned: bool


def pick(rows: list[dict[str, Any]], category: str | None, part: str) -> Pick | None:
    """What to offer for this kind of job at this part of the day: the music that played
    most in their finished sessions there (at least LEARNED_AFTER times; the latest wins a
    tie), else the kind's default, else nothing. Pure, over the session rows."""
    from themi_home.body_double_modes import part_of_day

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
        from themi_home.body_double_modes import part_of_day

        rows = self.db.query(
            "SELECT * FROM body_double_sessions WHERE member_id = ? AND ended_at IS NOT NULL",
            (session.member_id,),
        )
        return pick(rows, session.category, part_of_day(session.row["hour_of_week"]))

    def _last_playlist(self, session: Any) -> str | None:
        row = self.db.one(
            "SELECT music FROM body_double_sessions WHERE member_id = ? AND id != ? "
            "AND category IS ? AND music LIKE 'spotify:%' ORDER BY id DESC LIMIT 1",
            (session.member_id, session.id, session.category),
        )
        return str(row["music"]) if row else None

    async def _playlists(self, session: Any) -> list[dict[str, str]]:
        """F34i: their own playlists, read once for the session and kept on its row."""
        music = self.services.maybe(keys.music)
        if music is None:
            return []
        member = self.services.store.get_member(session.member_id)
        found = [{"uri": p.uri, "name": p.name, "link": p.link}
                 for p in await music.playlists(member)]  # fmt: skip
        found = ranked(found, session.category, self._last_playlist(session))
        if found:
            self.db.execute(
                "UPDATE body_double_sessions SET playlists = ? WHERE id = ?",
                (json.dumps(found), session.id),
            )
        return found

    def kept(self, session_id: int) -> list[dict[str, str]]:
        raw = self.db.scalar("SELECT playlists FROM body_double_sessions WHERE id = ?",
                             (session_id,))  # fmt: skip
        return list(json.loads(raw)) if raw else []

    async def offer(self, session: Any, text: str, buttons: list[Any]) -> tuple[str, list[Any]]:
        from themi.channels.events import Button

        chosen = self.choice(session)
        spotify_gone = self.services.maybe(keys.music) is None
        if chosen is not None and not chosen.music.startswith("builtin:") and spotify_gone:
            chosen = None  # Spotify isn't set up any more
        mine = await self._playlists(session)
        if chosen is not None:
            mine = [p for p in mine if p["uri"] != chosen.music]
        if chosen is None and not mine:
            return text, buttons
        tap = {"session": session.id, "text": text}
        offered = []
        if chosen is not None:
            line = offer_text(chosen)
            if mine and not chosen.learned:
                line = OFFER_MINE_TEXT.format(name=chosen.name)
            offered.append(
                Button(
                    "Play",
                    "music_offer",
                    {**tap, "music": chosen.music, "name": chosen.name, "action": "play"},
                )
            )
        else:
            line = OFFER_ONLY_MINE_TEXT
        offered += self._mine_buttons(tap, mine, 0, SHOWN)
        offered.append(Button("Not now", "music_offer", {**tap, "action": "skip"}))
        return f"{text}\n{line}", [*buttons, *offered]

    def _mine_buttons(self, tap: dict[str, Any], mine: list[dict[str, str]], start: int,
                      count: int) -> list[Any]:  # fmt: skip
        from themi.channels.events import Button

        out = [
            Button(p["name"][:40], "music_offer",
                   {**tap, "music": p["uri"], "name": p["name"], "action": "play"})
            for p in mine[start : start + count]
        ]  # fmt: skip
        if len(mine) > start + count:
            out.append(Button("More", "music_offer", {**tap, "action": "more",
                                                      "from": start + count}))  # fmt: skip
        return out

    async def on_button(self, event: Any) -> None:
        payload = event.button.payload
        member = self.services.store.get_member(event.member.id)
        said = str(payload.get("text", ""))
        if payload.get("action") == "more":  # F34i: the next page, from the session's copy
            from themi.channels.events import Button

            tap = {"session": payload.get("session"), "text": said}
            mine = self.kept(int(payload.get("session") or 0))
            buttons = [*self._mine_buttons(tap, mine, int(payload.get("from") or 0), PAGE),
                       Button("Not now", "music_offer", {**tap, "action": "skip"})]  # fmt: skip
            if event.button.message_id is not None:
                await self.services.outbox.edit(
                    member, event.button.message_id, f"{said}\n{MORE_TEXT}", buttons
                )
            return
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
        from themi_home.music import CATEGORY, PLAY

        outcome = await self.services.autonomy.stage(
            CATEGORY, member, f"Play {payload.get('name', '')} on Spotify",
            {"uri": payload["music"], "name": payload.get("name", "")}, PLAY,
            interactive=True, requested=True,
        )  # fmt: skip
        return outcome.message


class MusicOffersModule(Module):
    """BD5c: music that suits the task."""

    name = "music_offers"
    title = "Music for tasks"
    summary = "Offers music that suits the task during a body double session."
    requires = ("body_double",)

    def install(self, ctx: ModuleContext) -> None:
        from themi_home.body_double import (
            BodyDouble,  # at install: at the top it would be an import cycle
        )

        ctx.provide(MusicOffers(ctx.services, ctx.get(BodyDouble))).install()
