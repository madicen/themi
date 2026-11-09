"""What Themi the chameleon is doing on the session page (BD3b), picked in code.

The page draws one original character (`themi_home/web/static/chameleon/`) and a scene per mode;
this says which animation state it shows, as a flag in the page's state:

- `cheering` for a moment after a finished sprint block or guided step;
- on a sprint's break, one of the relaxed states (dozing, painting, stretching,
  doodling), changing every two minutes; `idle` while they chat on the page, as if
  listening;
- during a work block on a chores or tidying job, a sweep: one minute in every four;
- `idle` otherwise (in Silent Anchor's scene, that's reading).

CK5: the cook screen's scene (`pick_cooking_state`): watching from a stool by the counter;
stirring while a timer runs; cheering for a moment after [All done].

Never random: the same moment gives the same state, so it's tested like anything else.
"""

from __future__ import annotations

from datetime import datetime, timedelta

FLAGS = ("idle", "sweeping", "dozing", "painting", "stretching", "doodling", "cheering",
         "watching", "stirring")  # fmt: skip
RELAXED = ("dozing", "painting", "stretching", "doodling")
CHEER_FOR = timedelta(seconds=20)
RELAXED_EVERY = 2  # minutes
SWEEP_EVERY = 4  # minutes: one of them sweeping
CHAT_QUIET = timedelta(minutes=2)  # a page message this recent: still chatting
SWEEPY = ("chores", "tidy")


def pick_state(
    *,
    mode: str,
    category: str | None,
    phase: str,
    now: datetime,
    phase_started: datetime,
    cheer_until: datetime | None = None,
    chat_at: datetime | None = None,
) -> str:
    if cheer_until is not None and now < cheer_until:
        return "cheering"
    minutes = max(0, int((now - phase_started).total_seconds() // 60))
    if phase == "break":
        if chat_at is not None and now - chat_at < CHAT_QUIET:
            return "idle"
        return RELAXED[(minutes // RELAXED_EVERY) % len(RELAXED)]
    if phase == "work" and category in SWEEPY and minutes % SWEEP_EVERY == SWEEP_EVERY - 1:
        return "sweeping"
    return "idle"


def pick_cooking_state(
    *, now: datetime, timer_running: bool, cheer_until: datetime | None = None
) -> str:
    """CK5: the chameleon on the cook screen."""
    if cheer_until is not None and now < cheer_until:
        return "cheering"
    return "stirring" if timer_running else "watching"
