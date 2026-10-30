"""Per-person PDA calibration from in-chat feedback.

Shielding starts at strength 2 for everyone and moves one step at a time,
within 0 to 3, when someone says how a message landed:

- "too pushy", "that felt like pressure", "stop telling me…", or an angry face
  (😠 😡 😤 😣 🙄) on one of Themi's messages: stricter. A 👎 doesn't count: it
  marks a reply as the wrong thing (P4), or how a message landed (S5).
- "just tell me", "be direct", "that was fine", "you can be blunt": gentler.

Every change is logged with its reason. Turning shielding off entirely stays
a deliberate choice on the website.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from themi import clock
from themi.accounts import SYSTEM, AccountStore, Member
from themi.channels.pda import MAX_STRENGTH, MIN_STRENGTH

log = logging.getLogger(__name__)

STRICTER = re.compile(
    r"\b(too (?:pushy|bossy|demanding|much pressure)|felt like (?:pressure|nagging|an order)"
    r"|stop (?:telling|ordering|nagging) me|(?:don'?t|do not) boss me|quit nagging)\b",
    re.IGNORECASE,
)
GENTLER = re.compile(
    r"\b(just tell me|be (?:more )?direct|that was fine|that's fine to say"
    r"|you can be (?:blunt|direct)|no need to (?:soften|tiptoe)|less (?:fluff|padding))\b",
    re.IGNORECASE,
)
STRICTER_REACTIONS = frozenset({"😠", "😡", "😤", "😣", "🙄"})


@dataclass(frozen=True)
class CalibrationChange:
    old: int
    new: int
    reason: str


def feedback_direction(text: str) -> int:
    """+1 for "be gentler with me", -1 for "be more direct", 0 for neither."""
    if STRICTER.search(text):
        return 1
    if GENTLER.search(text):
        return -1
    return 0


class PdaCalibrator:
    def __init__(self, store: AccountStore) -> None:
        self.store = store

    def observe_text(self, member: Member, text: str) -> CalibrationChange | None:
        direction = feedback_direction(text)
        if direction == 0:
            return None
        return self._step(member, direction, f"said: {text[:80]}")

    def observe_reaction(self, member: Member, emoji: Sequence[str]) -> CalibrationChange | None:
        hits = [e for e in emoji if e in STRICTER_REACTIONS]
        if not hits:
            return None
        return self._step(member, 1, f"reacted {hits[0]} to a message")

    def _step(self, member: Member, direction: int, reason: str) -> CalibrationChange | None:
        current = self.store.get_member(member.id)
        new = max(MIN_STRENGTH, min(MAX_STRENGTH, current.pda_strength + direction))
        if new == current.pda_strength:
            return None
        self.store.update_settings(SYSTEM, member.id, pda_strength=new)
        self.store.db.execute(
            "INSERT INTO pda_calibration_log (member_id, old_strength, new_strength, reason, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (member.id, current.pda_strength, new, reason, clock.now().isoformat()),
        )
        log.info("PDA strength for member %s: %s -> %s", member.id, current.pda_strength, new)
        return CalibrationChange(current.pda_strength, new, reason)

    def history(self, member_id: int) -> list[CalibrationChange]:
        rows = self.store.db.query(
            "SELECT old_strength, new_strength, reason FROM pda_calibration_log "
            "WHERE member_id = ? ORDER BY id",
            (member_id,),
        )
        return [CalibrationChange(r["old_strength"], r["new_strength"], r["reason"]) for r in rows]
