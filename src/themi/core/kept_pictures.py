"""F34l: each member's latest picture, kept in memory (never on disk or in the database) for
a follow-up: their next two messages to the tool agent, within half an hour. F34o: a bug
report that says "that" takes it too."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from themi import clock
from themi.channels.events import Picture

KEPT_FOR = timedelta(minutes=30)
KEPT_TURNS = 2


@dataclass
class KeptPicture:
    picture: Picture
    at: datetime
    left: int = KEPT_TURNS


class KeptPictures:
    def __init__(self) -> None:
        self._kept: dict[int, KeptPicture] = {}

    def keep(self, member_id: int, picture: Picture) -> None:
        """A new picture replaces the one before."""
        self._kept[member_id] = KeptPicture(picture, clock.now())

    def peek(self, member_id: int) -> Picture | None:
        """Their latest picture if it's still kept, without using a turn of it up."""
        kept = self._kept.get(member_id)
        if kept is None:
            return None
        if kept.left <= 0 or clock.now() - kept.at > KEPT_FOR:
            del self._kept[member_id]
            return None
        return kept.picture

    def use(self, member_id: int) -> Picture | None:
        """Their latest picture for this turn; each use counts one of its turns."""
        picture = self.peek(member_id)
        if picture is not None:
            self._kept[member_id].left -= 1
        return picture
