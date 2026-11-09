"""The cook screen on /session (CK1): the cooking session as the page draws it.

There is no second session engine: `Cooking` (RC3a-c) is the one source of state, and the
chat's step card and this screen are two views of it. `state` is what the page shows, as
JSON, shaped like `BodyDouble.state` with `kind: "cooking"`; `act` is a tap on the page,
which calls the same methods the chat's buttons call and then redraws the chat's card.
Nothing about energy is ever in it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi_home.quantities import describe

if TYPE_CHECKING:
    from themi_home.cooking import Cooking, Session
    from themi_home.recipes import Recipe

log = logging.getLogger(__name__)

FIRED_SHOWN = timedelta(hours=2)  # a fired timer nobody tapped stays this long at most
MOVES = ("next", "back", "skip", "stop", "finish", "anyway", "tomorrow")


def session_for(cooking: Cooking, member: Member) -> Session | None:
    """Their own open session, or the family group's (open to either partner)."""
    return cooking.current(member) or cooking.current(member, in_group=True)


def may_tap(session: Session, member: Member) -> bool:
    return session.member_id == member.id or session.in_group


def state(cooking: Cooking, member: Member) -> dict[str, Any]:
    now = clock.now()
    session = session_for(cooking, member)
    if session is None:
        return {"active": False, "now": to_utc_iso(now)}
    recipe = cooking.recipes.get(session.recipe_id)
    if recipe is None:
        return {"active": False, "now": to_utc_iso(now)}
    return draw(cooking, session, recipe)


def draw(cooking: Cooking, session: Session, recipe: Recipe) -> dict[str, Any]:
    from themi_home.cooking import step_parts

    now = clock.now()
    parts = step_parts(recipe)
    out: dict[str, Any] = {
        "active": True,
        "kind": "cooking",
        "id": session.id,
        "seq": session.seq,
        "now": to_utc_iso(now),
        "phase": session.phase,
        "recipe": recipe.name,
        "heading": cooking.heading(session, recipe),
        "scale_words": describe(session.scale_said, session.scale) if session.scale != 1 else "",
        "group": session.in_group,
        "line": session.line,
        "step": None,
        "peek": "",
        "ahead": [],
        "gather": [],
        "prep": [],
        "offers": [],
    }
    if session.phase == "ready":
        out["ahead"] = [
            {"n": n, "text": a["text"], "overnight": bool(a["overnight"]),
             "done": bool(a.get("done"))}
            for n, a in enumerate(session.ahead)
        ]  # fmt: skip
    elif session.phase == "gather":
        lines = cooking.lines(session, recipe)
        out["gather"] = [
            {"n": n, "line": line, "group": source.group, "ticked": n in session.gathered}
            for n, (line, source) in enumerate(zip(lines, recipe.ingredients, strict=False))
        ]
    elif session.phase == "prep":
        out["prep"] = [
            {"n": n, "text": job["text"], "done": bool(job.get("done"))}
            for n, job in enumerate(session.prep)
        ]
    elif session.phase == "cook" and parts:
        n = min(session.step, len(parts) - 1)
        part = parts[n]
        out["step"] = {
            "index": n,
            "label": part.label,
            "text": part.text,
            "group": part.group,
            "words": f"Step {part.label} of {len(recipe.steps)}",
            "first": n == 0,
            "last": n >= len(parts) - 1,
        }
        if n + 1 < len(parts):
            nxt = parts[n + 1]
            out["peek"] = f"Next, step {nxt.label}: {nxt.text}"
        if cooking.timers is not None:
            from themi_home.cooking_timers import durations

            out["offers"] = [
                {"label": f"Timer {found.said}", "minutes": found.minutes, "step": part.label}
                for found in durations(part.text)
                if not found.reminder
            ]
    out["timers"] = timers(cooking, session)
    out["buttons"] = buttons(session, recipe)
    out["drawn"] = drawn(out)
    for timer in out["timers"]:  # the count before the page's script runs: not in `drawn`
        timer["text"] = span(seconds_left(timer["ends_at"]))
    return out


def timers(cooking: Cooking, session: Session) -> list[dict[str, Any]]:
    """The owner's timers: running, or fired and not yet tapped on the screen."""
    if cooking.timers is None:
        return []
    since = to_utc_iso(clock.now() - FIRED_SHOWN)
    rows = cooking.db.query(
        "SELECT * FROM cooking_timers WHERE member_id = ? AND cancelled_at IS NULL "
        "AND cleared_at IS NULL AND (fired_at IS NULL OR fired_at > ?) ORDER BY ends_at",
        (session.member_id, since),
    )
    return [
        {
            "id": row["id"],
            "label": row["label"] or f"Step {row['step']}",
            "ends_at": row["ends_at"],
            "fired": row["fired_at"] is not None,
        }
        for row in rows
    ]


def buttons(session: Session, recipe: Recipe) -> list[dict[str, str]]:
    """The moves under the step: the same choices as the chat's card."""
    from themi_home.cooking import step_parts

    if session.phase == "ready":
        if any(a["overnight"] for a in session.ahead):
            return [{"label": "Cook anyway", "action": "anyway"},
                    {"label": "Remind me tomorrow", "action": "tomorrow"}]  # fmt: skip
        return [{"label": "Done", "action": "next"}, {"label": "Skip", "action": "next"}]
    if session.phase == "gather":
        return [{"label": "All here", "action": "next"}]
    if session.phase == "prep":
        return [{"label": "Prep done", "action": "next"}, {"label": "Skip prep", "action": "skip"}]
    if session.phase != "cook":
        return []
    parts = step_parts(recipe)
    out = []
    if session.step > 0:
        out.append({"label": "Back", "action": "back"})
    if session.step < len(parts) - 1:
        out.append({"label": "Next", "action": "next"})
    else:
        out.append({"label": "All done", "action": "finish"})
    return out


def drawn(out: dict[str, Any]) -> str:
    """A short fingerprint of what the screen shows (not the clock), so the page redraws
    only when something changed: a move, or a timer firing between moves."""
    shown = {k: v for k, v in out.items() if k not in ("now", "drawn")}
    return hashlib.sha256(json.dumps(shown, sort_keys=True).encode()).hexdigest()[:12]


async def act(
    cooking: Cooking, member: Member, session_id: int, action: str, seq: int, form: dict[str, Any]
) -> bool:
    """A tap on the cook screen. False (and nothing done) when the session isn't theirs,
    has ended, or the tap came from an older screen than the session's `seq`."""
    session = cooking.get(session_id)
    if session is None or session.ended_at is not None or not may_tap(session, member):
        log.info("Cook screen tap %r on session %s refused: not theirs or over",
                 action, session_id)  # fmt: skip
        return False
    if seq != session.seq:
        log.info("Cook screen tap %r on session %s refused: seq %s, now %s",
                 action, session_id, seq, session.seq)  # fmt: skip
        return False
    recipe = cooking.recipes.get(session.recipe_id)
    if recipe is None:
        return False
    log.info("Cook screen tap %r on session %s", action, session_id)
    if action in ("tick", "untick"):
        tick(session, str(form.get("list", "gather")), _int(form.get("n")), action == "tick")
        await cooking.show(session)
    elif action == "anyway" and session.phase == "ready":
        session.phase = "gather"
        await cooking.show(session)
    elif action == "tomorrow" and session.phase == "ready":
        await cooking.remind_tomorrow(session)
    elif action == "skip" and session.phase == "prep":
        await cooking.after_prep(session)
        await cooking.show(session)
    elif action == "goto" and session.phase == "cook":
        await cooking.advance(session, f"goto:{str(form.get('to', '')).strip()}")
    elif action == "back" and session.phase != "cook":
        return False  # before the steps, Back isn't a move (it would go forward)
    elif action in ("all done", "all_done"):
        await cooking.advance(session, "finish" if session.phase == "cook" else "next")
    elif action == "timer" and cooking.timers is not None:
        minutes = _float(form.get("minutes"))
        if not 0 < minutes < 8 * 60:
            return False
        step = str(form.get("step", "")) or _step_label(session, recipe)
        cooking.timers.start(cooking._owner(session), session, recipe, step, minutes)
        await cooking.show(session)
    elif action in MOVES:
        await cooking.advance(session, action)
    else:
        return False
    return True


def tick(session: Session, which: str, n: int, on: bool) -> None:
    if which == "gather":
        if on and n not in session.gathered:
            session.gathered.append(n)
        elif not on and n in session.gathered:
            session.gathered.remove(n)
    elif which in ("ahead", "prep"):
        items = session.ahead if which == "ahead" else session.prep
        if 0 <= n < len(items):
            items[n] = {**items[n], "done": on}


def _step_label(session: Session, recipe: Recipe) -> str:
    from themi_home.cooking import step_parts

    parts = step_parts(recipe)
    return parts[min(session.step, len(parts) - 1)].label if parts else "1"


def _int(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return -1


def _float(value: Any) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def seconds_left(ends_at: str) -> float:
    return max(0.0, (datetime.fromisoformat(ends_at) - clock.now()).total_seconds())


def span(seconds: float) -> str:
    """ "9:59" or "1:05:00", as the page counts."""
    whole = round(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
