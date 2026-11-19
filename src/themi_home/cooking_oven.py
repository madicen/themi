"""The oven on the cook screen (OV4 to OV7, the Oven Module Plan).

When the oven is linked (`themi_home.oven`), the cook screen can work it, always by a tap:

- OV4: the look-ahead's preheat ("Step 4 wants the oven at 400°F. Start it now?") gets
  [Preheat]: Bake, or Convection Multi Bake when the step says convection or fan (only the
  lower oven has it), at the step's °F (°C turned into °F, to the nearest 5). A recipe that
  names the upper or lower oven gets that one; a plain Bake offers both. While an oven this
  session started is on, the screen shows it: "Lower oven 285°F of 400°F", "Preheated".
- OV5: a step's timer offers [Oven timer] too: Themi's timer and the oven's own.
- OV6: Stop or Finish, with an oven this session started still on, asks "Turn the oven off
  too?" [Turn off] [Leave it on].
- OV7: a step where dough rises offers [Proof in the oven]: Proof (85°F, the upper oven's
  only setting) with a timer for the step's time.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.core import keys
from themi.localtime import to_utc_iso
from themi_home.connectors.smarthq import LOWER, UPPER, SmartHQError
from themi_home.connectors.smarthq import events as ov
from themi_home.cooking import oven_heat

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi_home.cooking import Cooking, Session
    from themi_home.oven import OvenControl, Said
    from themi_home.recipes import Recipe

CONVECTION = re.compile(r"\b(?:convection|fan[- ](?:assisted|forced|oven)|fan oven)\b", re.I)
NAMED = re.compile(r"\b(?P<which>upper|top|lower|bottom)\s+oven\b", re.I)
WHICH = {"upper": UPPER, "top": UPPER, "lower": LOWER, "bottom": LOWER}
RISE = re.compile(
    r"\b(?:let (?:it |the dough |them )?(?:rise|proof)|(?:rise|proof)s? (?:until|for|in)|"
    r"until (?:it )?(?:has )?doubled|in a warm (?:place|spot)|second rise|first rise)\b",
    re.I,
)


def control(cooking: Cooking) -> OvenControl | None:
    """The oven, when it's linked."""
    found = cooking.services.maybe(keys.oven)
    return found if found is not None and found.linked() else None


def heat_for(text: str) -> tuple[int, int, str | None] | None:
    """A step's preheat as (mode, °F, the oven it names or None): its "preheat the oven to",
    or the temperature it bakes or roasts at (F49d)."""
    found = oven_heat(text)
    if found is None:
        return None
    temp, scale = found
    if scale == "C":
        temp = round((temp * 9 / 5 + 32) / 5) * 5
    mode = ov.CONV_MULTI_BAKE if CONVECTION.search(text) else ov.BAKE
    named = NAMED.search(text)
    return mode, temp, WHICH[named.group("which").lower()] if named else None


def _part_text(recipe: Recipe, part: int) -> str:
    from themi_home.cooking import step_parts

    parts = step_parts(recipe)
    return parts[part].text if 0 <= part < len(parts) else ""


def preheat_buttons(cooking: Cooking, recipe: Recipe, key: str) -> list[dict[str, Any]]:
    """OV4: the strip's [Preheat] buttons for a look-ahead preheat ("preheat:3")."""
    oven = control(cooking)
    kind, _, part = key.partition(":")
    if oven is None or kind != "preheat" or not part.isdigit():
        return []
    found = heat_for(_part_text(recipe, int(part)))
    if found is None:
        return []
    mode, temp, named = found
    if named is not None:
        cavities = [named]
    elif mode == ov.BAKE:
        cavities = [LOWER, UPPER]  # the bigger one first
    else:
        cavities = [c for c in (LOWER, UPPER) if mode in ov.OFFERS[c]]
    out = []
    for cavity in cavities:
        if oven.oven(cavity) is None or mode not in ov.OFFERS[cavity]:
            continue
        label = "Preheat" if len(cavities) == 1 else f"Preheat {ov.NAMES[cavity]}"
        if mode != ov.BAKE:
            label += f" ({ov.mode_words(mode)})"
        out.append({"label": label, "oven": cavity, "mode": mode, "temp": temp, "key": key})
    return out


def oven_line(cooking: Cooking, session: Session) -> str:
    """OV4: an oven this session started, as it last read."""
    oven = control(cooking)
    if oven is None:
        return ""
    for cavity in (LOWER, UPPER):
        found = oven.oven(cavity)
        heatup = oven.open_heatup(found) if found is not None else None
        if found is None or heatup is None or heatup["session_id"] != session.id:
            continue
        last = oven.watcher.last(found)
        if last is None or not last.on:
            continue
        if last.state == ov.STATE_PROOF:
            return f"{found.title} proofing at 85°F"
        if last.preheating:
            now = f"{last.temp_f}°F of " if last.temp_f and last.temp_f > 100 else "heating to "
            return f"{found.title} {now}{last.set_f}°F"
        return f"{found.title} preheated to {last.set_f}°F"
    return ""


def started_here(cooking: Cooking, session: Session) -> list[str]:
    """The ovens this session started that are still on (OV6)."""
    oven = control(cooking)
    if oven is None:
        return []
    out = []
    for cavity in (LOWER, UPPER):
        found = oven.oven(cavity)
        heatup = oven.open_heatup(found) if found is not None else None
        if found is not None and heatup is not None and heatup["session_id"] == session.id:
            out.append(cavity)
    return out


async def preheat(
    cooking: Cooking, member: Member, session: Session, form: dict[str, Any]
) -> Said | None:
    """OV4: a [Preheat] tap. None when the tap doesn't say a real preheat."""
    oven = control(cooking)
    found = oven.oven(str(form.get("oven", ""))) if oven is not None else None
    try:
        mode, temp = int(str(form.get("mode", ""))), int(str(form.get("temp", "")))
    except ValueError:
        return None
    if oven is None or found is None:
        return None
    return await oven.heat(
        member, found, mode, temp, offered_at=_when(form.get("at")), session_id=session.id
    )


def _names(cavities: list[str]) -> str:
    if len(cavities) == 1:
        return f"the {ov.NAMES[cavities[0]]}"
    return "both ovens"


def off_question(cooking: Cooking, session: Session) -> str:
    """OV6: "The lower oven is still on. Turn it off too?", while an oven this session
    started is on and nobody's answered; "" otherwise."""
    if session.ended_at is None or "oven" in session.wrap:
        return ""
    on = started_here(cooking, session)
    if not on:
        return ""
    names = _names(on)
    still = f"{names[0].upper()}{names[1:]} {'is' if len(on) == 1 else 'are'} still on."
    return f"{still} Turn {'it' if len(on) == 1 else 'them'} off too?"


async def ask_off(cooking: Cooking, session: Session, *, in_chat: bool) -> None:
    """OV6: Stop or Finish with an oven this session started still on. The screen asks
    when it's open; otherwise the chat does."""
    question = off_question(cooking, session)
    if not question or not in_chat:
        return
    from themi.channels.events import Button
    from themi.channels.outbox import Priority
    from themi_home.oven import BUTTON

    tap = {"session": session.id}
    await cooking.services.outbox.send(
        cooking.services.store.get_member(session.member_id),
        question,
        priority=Priority.REPLY,
        buttons=[
            Button("Turn off", BUTTON, {**tap, "do": "off_session"}),
            Button("Leave it on", BUTTON, {**tap, "do": "leave_session"}),
        ],
        kind="oven",
    )


async def answer_off(cooking: Cooking, member: Member, session: Session, off: bool) -> str:
    """OV6: [Turn off] turns off every oven this session started; [Leave it on] keeps them on
    (the oven's left-on warning still comes). Asked once."""
    oven = control(cooking)
    if oven is None or "oven" in session.wrap:
        return ""
    session.wrap["oven"] = "off" if off else "left"
    cooking.save_wrap(session)
    on = started_here(cooking, session)
    if not off:
        return f"Okay, leaving {_names(on)} on." if on else ""
    said = []
    for cavity in on:
        found = oven.oven(cavity)
        if found is not None:
            said.append((await oven.off(member, found)).words)
    return " ".join(said)


def proof_offer(cooking: Cooking, session: Session, recipe: Recipe) -> dict[str, Any] | None:
    """OV7: the step they're on rises: [Proof in the oven], with its time when it says one.
    None without the upper oven, or with it on."""
    oven = control(cooking)
    if oven is None or session.phase != "cook" or session.ended_at is not None:
        return None
    upper = oven.oven(UPPER)
    if upper is None:
        return None
    text = _part_text(recipe, session.step)
    if not RISE.search(text):
        return None
    last = oven.watcher.last(upper)
    if last is not None and last.on:
        return None
    from themi_home.cooking_timers import durations

    found = next((d for d in durations(text) if not d.reminder), None)
    return {"label": "Proof in the oven", "minutes": found.minutes if found else 0}


async def proof(
    cooking: Cooking, member: Member, session: Session, recipe: Recipe, form: dict[str, Any]
) -> Said | None:
    """OV7: Proof (85°F) on the upper oven, only when it's off, and a timer for the step."""
    oven = control(cooking)
    upper = oven.oven(UPPER) if oven is not None else None
    if oven is None or upper is None:
        return None
    from themi_home.oven import Said as Told

    try:
        now = await oven.watcher.read(upper)
    except SmartHQError:
        now = None  # heat() below says what's wrong
    if now is not None and now.on:
        return Told(False, f"The upper oven is on ({ov.state_words(now)}), so it can't proof now.")
    said = await oven.heat(
        member, upper, ov.PROOF, ov.PROOF_F, offered_at=_when(form.get("at")),
        session_id=session.id,
    )  # fmt: skip
    minutes = 0.0
    try:
        minutes = float(str(form.get("minutes") or 0))
    except ValueError:
        minutes = 0.0
    if said.ok and minutes > 0 and cooking.timers is not None:
        from themi_home.cooking_screen import _step_label

        step = _step_label(session, recipe)
        cooking.timers.start(cooking._owner(session), session, recipe, step, minutes)
        from themi_home.cooking_timers import _short

        return Told(True, f"{said.words} And a {_short(minutes)} timer for the rise.")
    return said


def has_timer(cooking: Cooking) -> bool:
    """OV5: the oven's linked, with its (upper) kitchen timer."""
    oven = control(cooking)
    return oven is not None and oven.oven(ov.TIMER_OVEN) is not None


async def oven_timer(cooking: Cooking, member: Member, session: Session, minutes: float) -> str:
    """OV5: the oven's timer for the cook-screen timer just started (whole minutes, rounded
    up, as the oven counts), tied to it so either follows the other."""
    oven = control(cooking)
    timer_id = cooking.db.scalar(
        "SELECT MAX(id) FROM cooking_timers WHERE session_id = ?", (session.id,)
    )
    if oven is None or timer_id is None:
        return "Timer set."
    said = await oven.set_timer(member, math.ceil(minutes), link=int(timer_id))
    return "Timer set, and the oven's timer too." if said.ok else f"Timer set. {said.words}"


def drawn_at() -> str:
    """When the screen drew its oven buttons: a tap from a screen older than the oven
    module's `STALE` is refused."""
    return to_utc_iso(clock.now())


def _when(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
