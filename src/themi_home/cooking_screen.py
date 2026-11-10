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
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi_home.body_double_scene import CHEER_FOR, pick_cooking_state
from themi_home.cooking_links import MORE, shown
from themi_home.cooking_timers import PRESETS
from themi_home.cooking_wrap import WRAP_TAPS
from themi_home.quantities import AMOUNT, BRACKET, LEADING_WORDS, NeedsYield, fraction, scale_for

if TYPE_CHECKING:
    from themi_home.cooking import Cooking, Session
    from themi_home.recipes import Recipe

log = logging.getLogger(__name__)

FIRED_SHOWN = timedelta(hours=2)  # a fired timer nobody tapped stays this long at most
MOVES = ("next", "back", "skip", "stop", "finish", "anyway", "tomorrow")
TIMER_TAPS = ("timer_add", "timer_cancel", "timer_clear", "timers_keep", "timers_cancel")
AFTER_END = (*TIMER_TAPS, *WRAP_TAPS)  # what an ended session's screen can still do
OPTIONAL = re.compile(
    r"\b(?:optional|if (?:you['\u2019]d like|you like|you want|desired|using|wanted))\b",
    re.IGNORECASE,
)  # CK7: a step that can be left out
SCALES = (("½", "half", 0.5), ("1\u00d7", "", 1.0), ("2\u00d7", "double", 2.0))  # CK2's switcher
HEADLINE_MAX = 90  # characters: a longer first sentence stays in the body (CK12)


@dataclass(frozen=True)
class Tapped:
    """What a tap did: `ok` (False: nothing, it was stale or not theirs), and a line the
    screen says once ("Now for 6.")."""

    ok: bool
    said: str = ""

    def __bool__(self) -> bool:
        return self.ok


def session_for(cooking: Cooking, member: Member) -> Session | None:
    """Their own open session, or the family group's (open to either partner)."""
    return cooking.current(member) or cooking.current(member, in_group=True)


def may_tap(session: Session, member: Member) -> bool:
    return session.member_id == member.id or session.in_group


def still_shown(cooking: Cooking, session: Session) -> bool:
    """An ended session stays on the screen while it has timers to show (kept ones, until
    they fire and are tapped), or a wrap-up offer not yet answered (CK6)."""
    from themi_home.cooking_wrap import offer

    recipe = cooking.recipes.get(session.recipe_id)
    return bool(timers(cooking, session)) or (
        recipe is not None and offer(cooking, session, recipe) is not None
    )


def state(cooking: Cooking, member: Member) -> dict[str, Any]:
    now = clock.now()
    session = session_for(cooking, member)
    if session is None:
        ended = cooking.recent_ended(member)
        session = ended if ended is not None and still_shown(cooking, ended) else None
    if session is None:
        return {"active": False, "now": to_utc_iso(now)}
    recipe = cooking.recipes.get(session.recipe_id)
    if recipe is None:
        return {"active": False, "now": to_utc_iso(now)}
    return draw(cooking, session, recipe, member)


def draw(cooking: Cooking, session: Session, recipe: Recipe, viewer: Member) -> dict[str, Any]:
    from themi_home.cooking import step_parts

    now = clock.now()
    parts = step_parts(recipe)
    prefs = cooking.preferences(viewer.id)
    # CK7: a low level at the start leans the screen lighter. Only the effects are in the
    # state, never why.
    lighter = session.energy_at_start == "low"
    out: dict[str, Any] = {
        "active": True,
        "kind": "cooking",
        "id": session.id,
        "seq": session.seq,
        "now": to_utc_iso(now),
        "phase": session.phase,
        "recipe": recipe.name,
        "section": recipe.subsection or recipe.section,  # CK12: the header's quiet line
        "step_total": len(recipe.steps),
        "heading": cooking.heading(session, recipe),
        "scale_words": scale_words(session.scale_said, session.scale),
        "scales": scales(session, recipe),
        "group": session.in_group,
        "line": session.line,
        "step": None,
        "peek": "",
        "ahead": [],
        "gather": [],
        "prep": [],
        "offers": [],
        "view": {
            "text_size": prefs.cooking_text_size,
            "theme": prefs.cooking_theme,
            "steps_view": prefs.cooking_steps_view,
            "voice": prefs.cooking_voice,  # CK8: push-to-talk turned on
        },
        "skip_checklist": lighter and session.phase == "gather",
        "steps": [],
        "strip_steps": [],
        "next_title": "",
    }
    if session.phase == "ready":
        out["ahead"] = [
            {"n": n, "text": a["text"], "overnight": bool(a["overnight"]),
             "done": bool(a.get("done"))}
            for n, a in enumerate(session.ahead)
        ]  # fmt: skip
    elif session.phase == "gather":
        from themi_home.cooking_wrap import might_be_out

        lines = cooking.lines(session, recipe)
        out_now = might_be_out(cooking, recipe)  # CK6
        items = cooking.groceries.known(recipe)
        out["gather"] = [
            {"n": n, "line": line, "group": source.group, "ticked": n in session.gathered,
             "maybe_out": n in out_now, "item": items[n].item if n < len(items) else ""}
            for n, (line, source) in enumerate(zip(lines, recipe.ingredients, strict=False))
        ]  # fmt: skip
    elif session.phase == "prep":
        out["prep"] = [
            {"n": n, "text": job["text"], "done": bool(job.get("done"))}
            for n, job in enumerate(session.prep)
        ]
    elif session.phase == "cook" and parts:
        n = min(session.step, len(parts) - 1)
        part = parts[n]
        titles = cooking.titles.titles(recipe)  # CK12: the step strip
        here = step_index(part.label)
        headline, rest = split_headline(part.text)
        out["step"] = {
            "index": n,
            "label": part.label,
            "text": part.text,
            "headline": headline,
            "rest": rest,
            "title": titles[here] if here < len(titles) else "",
            "group": part.group,
            "words": f"Step {part.label} of {len(recipe.steps)}",
            "first": n == 0,
            "last": n >= len(parts) - 1,
            "folded": lighter and bool(OPTIONAL.search(part.text)),
        }
        out["strip_steps"] = [
            {"n": i + 1, "title": title, "done": i < here, "current": i == here}
            for i, title in enumerate(titles)
        ]
        if prefs.cooking_steps_view == "all":
            out["steps"] = [
                {"label": p.label, "text": p.text, "current": i == n,
                 "done": i < n, "folded": lighter and i != n and bool(OPTIONAL.search(p.text))}
                for i, p in enumerate(parts)
            ]  # fmt: skip
        out["amounts"] = amounts(cooking, session, recipe, part.label, viewer)
        if n + 1 < len(parts):
            nxt = parts[n + 1]
            out["peek"] = f"Next, step {nxt.label}: {nxt.text}"
            after = step_index(nxt.label)
            out["next_title"] = (
                titles[after] if after != here and after < len(titles) else f"step {nxt.label}"
            )
        if cooking.timers is not None:
            from themi_home.cooking_timers import durations

            out["offers"] = [
                {"label": f"Timer {found.said}", "minutes": found.minutes, "step": part.label}
                for found in durations(part.text)
                if not found.reminder
            ]
    from themi_home.cooking_ahead import strip

    out["strip"] = (
        strip(cooking, session, recipe, must_only=lighter) if session.ended_at is None else None
    )
    out["timers"] = timers(cooking, session)
    running = [t for t in out["timers"] if not t["fired"]]
    out["ended"] = session.ended_at is not None
    out["outcome"] = session.outcome or ""
    out["ask_timers"] = out["ended"] and bool(running) and "timers" not in session.wrap
    from themi_home.cooking_wrap import offer

    out["wrap"] = offer(cooking, session, recipe) if out["ended"] else None
    out["soonest"] = running[0]["ends_at"] if running else ""
    out["presets"] = list(PRESETS)
    out["chime_volume"] = cooking.preferences(viewer.id).cooking_chime_volume
    out["buttons"] = buttons(session, recipe)
    out["scene"] = pick_cooking_state(
        now=now,
        timer_running=bool(running),
        cheer_until=session.ended_at + CHEER_FOR
        if session.ended_at is not None and session.outcome == "finished"
        else None,
    )  # CK5: the chameleon
    out["chat"] = cooking.page_chat(session)
    out["music"] = music(cooking, session, viewer)
    out["meta"] = meta(out)
    out["drawn"] = drawn(out)
    for timer in out["timers"]:  # the count before the page's script runs: not in `drawn`
        left = seconds_left(timer["ends_at"])
        timer["text"] = span(left)
        timer["of"] = span(timer["seconds"])
    return out


def meta(out: dict[str, Any]) -> str:
    """CK12: the header's quiet line: "for 4 · 6 steps · Dinner"."""
    batch = out["scale_words"] or (f"for {out['scales']['for']}" if out["scales"]["for"] else "")
    total = out["step_total"]
    count = f"{total} step{'' if total == 1 else 's'}" if total else ""
    return " \u00b7 ".join(part for part in (batch, count, out["section"]) if part)


def step_index(label: str) -> int:
    """The recipe step (0-based) a part's label is from: "3" and "3b" are step 3."""
    found = re.match(r"\d+", label)
    return int(found.group()) - 1 if found else 0


def amounts(
    cooking: Cooking, session: Session, recipe: Recipe, label: str, viewer: Member
) -> dict[str, Any]:
    """CK2: the lines this step uses, at the session's scale, and every line for the
    drawer, grouped as the recipe groups them. Used lines are marked."""
    units = cooking.preferences(viewer.id).cooking_units
    scaled = cooking.lines(session, recipe)
    links = cooking.links.links(recipe, cooking.groceries.known(recipe))

    def line(n: int) -> dict[str, Any]:
        text = shown(scaled[n], units)
        name, amount = name_and_amount(text)
        return {"n": n, "line": text, "name": name, "amount": amount, "used": n in session.used}

    groups: list[dict[str, Any]] = []
    for n, source in enumerate(recipe.ingredients):
        if not groups or groups[-1]["group"] != source.group:
            groups.append({"group": source.group, "lines": []})
        groups[-1]["lines"].append(line(n))
    uses = [line(n) for n in links.get(step_index(label), []) if n < len(scaled)]
    added = sum(1 for a in uses if a["used"])  # CK12: "2 of 5 added"
    return {"uses": uses, "groups": groups, "units": units, "added": added, "total": len(uses)}


def name_and_amount(line: str) -> tuple[str, str]:
    """CK12: "2 cloves garlic, minced" as ("Garlic, minced", "2 cloves"), for the ingredient
    card's two columns. A line with no amount up front is all name."""
    prefix = LEADING_WORDS.match(line)
    start = prefix.end() if prefix else 0
    found = AMOUNT.match(line, start)
    if found is None:
        return line, ""
    end = found.end()
    bracket = BRACKET.match(line, end)
    if bracket is not None:
        end = bracket.end()
    while more := MORE.match(line, end):  # "1 Tbsp + 1 tsp": one amount
        end = more.end()
    name = (line[:start] + line[end:]).strip(" ,;:-")
    name = re.sub(r"^of\s+", "", name, flags=re.IGNORECASE)
    if not name:
        return line, ""
    return name[:1].upper() + name[1:], line[start:end].strip()


def split_headline(text: str) -> tuple[str, str]:
    """CK12: the step's first sentence, set large, and the rest under it, words unchanged.
    One sentence, or a first one too long to read as a headline: all of it is the headline."""
    from themi_home.cooking import SENTENCE

    first, *more = SENTENCE.split(text.strip(), maxsplit=1)
    if not more or len(first) > HEADLINE_MAX:
        return text.strip(), ""
    return first, more[0]


def scale_words(said: str, factor: float) -> str:
    """How the screen names the batch: "for 6", "half", "double", "1.5 times"; "" as written."""
    found = re.match(r"^for (\d+)", said.strip().lower())
    if found:
        return f"for {found.group(1)}"
    names = {1.0: "", 0.5: "half", 2.0: "double", 3.0: "triple"}
    return names.get(factor, f"{fraction(factor)}\u00d7")


def scales(session: Session, recipe: Recipe) -> dict[str, Any]:
    """CK2: the scale switcher: ½, 1, 2, and "for N" (when the recipe says how many)."""
    chosen = session.scale_said.strip().lower().startswith("for ")
    return {
        "options": [
            {"label": label, "said": said, "on": not chosen and abs(session.scale - f) < 1e-9}
            for label, said, f in SCALES
        ],
        "makes": recipe.makes,
        "for": round(session.scale * recipe.makes) if recipe.makes else None,
        "chosen_for": chosen,
    }


def now_words(said: str, factor: float) -> str:
    words = scale_words(said, factor)
    if not words:
        return "Now as written."
    if words.startswith("for "):
        return f"Now {words}."
    return f"Now {words} the recipe." if words in ("half", "double", "triple") else f"Now {words}."


def music(cooking: Cooking, session: Session, viewer: Member) -> dict[str, Any] | None:
    """CK5: the body double page's music, with BD5c's suggestion for cooking."""
    from themi.core import keys
    from themi_home.body_double_music import DEFAULTS, LOOPS

    bd = cooking.services.maybe(keys.body_double)
    if bd is None:
        return None
    found = dict(bd.music_state(viewer))
    usual = DEFAULTS["cooking"].removeprefix("builtin:")
    name = LOOPS[found["sound"]].name
    found["offer"] = (
        f"Some {name.lower()} while you cook?" if found["sound"] == usual
        else f"{name} again, like last time?"
    )  # fmt: skip
    found["spotify"] = cooking.playlists.get(session.id, [])
    return found


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
            "seconds": round(float(row["minutes"]) * 60),  # CK12: "of 8:00", and the bar
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
        return [{"label": "Done", "action": "next"}, {"label": "Skip", "action": "skip"}]
    if session.phase == "gather":
        if session.energy_at_start == "low":  # CK7: the checklist is optional today
            return [{"label": "Skip the checklist", "action": "skip"},
                    {"label": "All here", "action": "next"}]  # fmt: skip
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


UNDRAWN = ("now", "drawn", "scene", "chat", "music", "line")  # the company bar's, kept live


def drawn(out: dict[str, Any]) -> str:
    """A short fingerprint of what the regions show (not the clock), so the page redraws
    them only when something changed: a move, or a timer firing between moves. The company
    bar (the scene, Themi's line, music, Ask Themi) isn't redrawn: its music keeps playing."""
    shown = {k: v for k, v in out.items() if k not in UNDRAWN}
    return hashlib.sha256(json.dumps(shown, sort_keys=True).encode()).hexdigest()[:12]


async def act(
    cooking: Cooking, member: Member, session_id: int, action: str, seq: int, form: dict[str, Any]
) -> Tapped:
    """A tap on the cook screen. Not ok (and nothing done) when the session isn't theirs,
    has ended, or the tap came from an older screen than the session's `seq`."""
    session = cooking.get(session_id)
    over = session is not None and session.ended_at is not None and action not in AFTER_END
    if session is None or over or not may_tap(session, member):
        log.info("Cook screen tap %r on session %s refused: not theirs or over",
                 action, session_id)  # fmt: skip
        return Tapped(False)
    if seq != session.seq:
        log.info("Cook screen tap %r on session %s refused: seq %s, now %s",
                 action, session_id, seq, session.seq)  # fmt: skip
        return Tapped(False)
    recipe = cooking.recipes.get(session.recipe_id)
    if recipe is None:
        return Tapped(False)
    log.info("Cook screen tap %r on session %s", action, session_id)
    said = ""
    if action in TIMER_TAPS:
        return Tapped(timer_tap(cooking, session, action, form))
    if action in WRAP_TAPS:
        from themi_home import cooking_wrap

        done, said = await cooking_wrap.tap(cooking, session, recipe, action, form)
        return Tapped(done, said)
    if action in ("out_groceries", "out_swap"):  # CK6: a "might be out" line
        from themi_home import cooking_wrap

        n = _int(form.get("n"))
        items = cooking.groceries.known(recipe)
        if session.phase != "gather" or n not in cooking_wrap.might_be_out(cooking, recipe):
            return Tapped(False)
        if action == "out_groceries":
            return Tapped(True, await cooking_wrap.to_groceries(cooking, member, items[n].item))
        session.wrap["swap"] = items[n].item
        cooking.save_wrap(session)
        return Tapped(True, cooking_wrap.swap_question(items[n].item, recipe))
    if action == "scale":
        return await rescale(cooking, session, recipe, form)
    if action in ("ahead_done", "ahead_later"):  # CK4: the look-ahead strip
        from themi_home.cooking_ahead import answer

        if not answer(session, str(form.get("key", "")), action.removeprefix("ahead_")):
            return Tapped(False)
        cooking.save(session)
        return Tapped(True)
    if action == "use":
        n = _int(form.get("n"))
        if not 0 <= n < len(recipe.ingredients):
            return Tapped(False)
        if n in session.used:
            session.used.remove(n)
        else:
            session.used.append(n)
        cooking.save(session)  # CK12: a tick shows on the screen only, not on the chat's card
    elif action in ("tick", "untick"):
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
        return Tapped(False)  # before the steps, Back isn't a move (it would go forward)
    elif action in ("all done", "all_done"):
        await cooking.advance(session, "finish" if session.phase == "cook" else "next")
    elif action == "timer" and cooking.timers is not None:
        minutes = _float(form.get("minutes") or form.get("typed"))
        if not 0 < minutes < 8 * 60:
            return Tapped(False)
        step = str(form.get("step", "")) or _step_label(session, recipe)
        label = str(form.get("label", "")).strip() or None
        cooking.timers.start(cooking._owner(session), session, recipe, step, minutes, label)
        await cooking.show(session)
    elif action in MOVES:
        await cooking.advance(session, action)
    else:
        return Tapped(False)
    return Tapped(True, said)


async def rescale(
    cooking: Cooking, session: Session, recipe: Recipe, form: dict[str, Any]
) -> Tapped:
    """CK2: ½, 1, 2 or "for N" from the screen. Every amount rescales; the screen says
    once what it is now, and the chat's card is redrawn with it."""
    said = str(form.get("said", "")).strip()
    if str(form.get("for", "")).strip():
        said = f"for {str(form.get('for')).strip()}"
    try:
        factor = scale_for(said, recipe.makes)
    except NeedsYield:
        return Tapped(False, f"{recipe.name} doesn't say how many it makes. Tell Themi in "
                             "chat, or pick ½ or 2\u00d7.")  # fmt: skip
    except ValueError:
        return Tapped(False, "That isn't an amount to scale by.")
    session.scale, session.scale_said = factor, said
    await cooking.show(session)
    return Tapped(True, now_words(said, factor))


def timer_tap(cooking: Cooking, session: Session, action: str, form: dict[str, Any]) -> bool:
    """CK3: [+1] [+5] [Cancel] on a timer's card, a tap on a fired one, and the ending's
    [Keep timers] [Cancel them]: the same methods as typed "add 2 minutes", "cancel the
    timer", and the chat's buttons."""
    timers = cooking.timers
    if timers is None:
        return False
    owner = session.member_id
    timer_id = _int(form.get("timer"))
    if action == "timer_add":
        return timers.add(owner, timer_id, _int(form.get("minutes"))) is not None
    if action == "timer_cancel":
        return timers.cancel(owner, timer_id)
    if action == "timer_clear":
        return timers.clear(owner, timer_id)
    if session.ended_at is None or "timers" in session.wrap:
        return False  # the ending's question, asked once
    member = cooking._owner(session)
    if action == "timers_cancel":
        timers.cancel_all(member)
    cooking.answer_timers(member, kept=action == "timers_keep")
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
