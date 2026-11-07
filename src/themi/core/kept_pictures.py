"""F34l: each member's latest picture, kept in memory (never on disk or in the database) for
a follow-up: their next two messages to the tool agent, within half an hour. F34o: a bug
report that says "that" takes it too.

F34mb: pictures sent close together (one album, or each under a minute after the one
before) are kept together, in order, up to `MOST_TOGETHER`: two pages of one recipe are
one thing (bug #184). The group before the latest is remembered too, for "here's the other
page" sent a little later."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from themi import clock
from themi.channels.events import Picture

KEPT_FOR = timedelta(minutes=30)
KEPT_TURNS = 2
TOGETHER = timedelta(minutes=1)  # F34mb: a picture this soon after the last joins its group
MOST_TOGETHER = 4


@dataclass
class KeptPicture:
    """A group of pictures sent close together (one, usually)."""

    pictures: list[Picture]
    at: datetime  # when the latest of them came
    left: int = KEPT_TURNS
    albums: set[str] = field(default_factory=set)

    @property
    def picture(self) -> Picture:
        return self.pictures[-1]


class KeptPictures:
    def __init__(self) -> None:
        self._kept: dict[int, KeptPicture] = {}
        self._before: dict[int, KeptPicture] = {}

    def keep(self, member_id: int, *pictures: Picture, album: str = "") -> bool:
        """Keep a message's pictures. They join the group before them when they're part of
        its album or came within `TOGETHER` of its latest; otherwise they start a new
        group, and the old one is remembered as the one before. True when they joined an
        album already kept (its other pictures came in an earlier update)."""
        if not pictures:
            return False
        now = clock.now()
        kept = self._live(member_id)
        joined_album = kept is not None and bool(album) and album in kept.albums
        if kept is not None and (joined_album or now - kept.at <= TOGETHER):
            kept.pictures = [*kept.pictures, *pictures][-MOST_TOGETHER:]
            kept.at = now
            kept.left = KEPT_TURNS
        else:
            if kept is not None:
                self._before[member_id] = kept
            kept = KeptPicture(list(pictures)[-MOST_TOGETHER:], now)
            self._kept[member_id] = kept
        if album:
            kept.albums.add(album)
        return joined_album

    def peek(self, member_id: int) -> Picture | None:
        """Their latest picture if it's still kept, without using a turn of it up."""
        kept = self._live(member_id)
        return kept.picture if kept is not None else None

    def group(self, member_id: int) -> tuple[Picture, ...]:
        """Their latest group of pictures, in order, without using a turn of it up."""
        kept = self._live(member_id)
        return tuple(kept.pictures) if kept is not None else ()

    def before(self, member_id: int) -> tuple[Picture, ...]:
        """The group they sent before the latest one, if still within `KEPT_FOR`."""
        kept = self._before.get(member_id)
        if kept is None or clock.now() - kept.at > KEPT_FOR:
            self._before.pop(member_id, None)
            return ()
        return tuple(kept.pictures)

    def use(self, member_id: int) -> tuple[Picture, ...]:
        """Their latest group for this turn; each use counts one of its turns."""
        kept = self._live(member_id)
        if kept is None:
            return ()
        kept.left -= 1
        return tuple(kept.pictures)

    def _live(self, member_id: int) -> KeptPicture | None:
        kept = self._kept.get(member_id)
        if kept is None:
            return None
        if kept.left <= 0 or clock.now() - kept.at > KEPT_FOR:
            del self._kept[member_id]
            return None
        return kept
