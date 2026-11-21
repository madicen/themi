"""PT6a: how Themi says what a parcel is doing (the Themi Package Tracking Plan, "What the
family sees"): one set of sentences for the wall's note, the morning message and chat.

Every sentence names the shop only, never what's in the parcel and never its tracking
number. A carrier's own words (a problem) are its plain text, cut short when it was kept.
Times are the family's; a time is said only when a carrier gave it (an email's arrival
isn't when the parcel came).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi.clock import now as clock_now
from themi.core import keys
from themi.core.tools import ToolContext, tool
from themi.core.wording import and_list
from themi_google.deliveries import Parcel

CARRIERS = {"ups": "UPS", "usps": "USPS", "fedex": "FedEx", "amazon": "Amazon"}
ATTEMPTED = re.compile(
    r"attempt|notice left|not available|no one|no access|missed|unable to deliver", re.I
)
COUNTS = ("Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine")


def count_word(n: int) -> str:
    """ "Two", "Three", ... "Several"."""
    return COUNTS[n - 2] if 2 <= n <= 9 else "Several"


def carrier_name(p: Parcel) -> str:
    return CARRIERS.get(p.carrier, "The carrier") if len(p.carriers) == 1 else "The carrier"


def clock(hhmm: str, *, ampm: bool = True) -> str:
    """ "14:15" -> "2:15 pm", "14:00" -> "2 pm"."""
    hour, minute = (int(x) for x in hhmm.split(":"))
    shown = f"{hour % 12 or 12}" + (f":{minute:02d}" if minute else "")
    return f"{shown} {'am' if hour < 12 else 'pm'}" if ampm else shown


def window(p: Parcel) -> str:
    """ "between 2:15 and 4:15 pm", "between 10 am and 2 pm"; "" for none."""
    if not (p.window_start and p.window_end):
        return ""
    same_half = (int(p.window_start[:2]) < 12) == (int(p.window_end[:2]) < 12)
    start = clock(p.window_start, ampm=not same_half)
    return f"between {start} and {clock(p.window_end)}"


def day_words(day: date, today: date) -> str:
    """ "today", "tomorrow", "Friday", or "on 3 November" further off."""
    if day == today:
        return "today"
    if day == today + timedelta(days=1):
        return "tomorrow"
    if today < day <= today + timedelta(days=6):
        return f"{day:%A}"
    return f"on {day.day} {day:%B}"


def problem(p: Parcel, today: date) -> str:
    """ "UPS couldn't deliver the parcel from Chewy. It's now due tomorrow." """
    if ATTEMPTED.search(p.problem):
        text = f"{carrier_name(p)} couldn't deliver the parcel from {p.shop}."
    elif p.problem:
        text = f"The delivery from {p.shop} has a hitch ({p.problem})."
    else:
        text = f"The delivery from {p.shop} has a hitch."
    if p.expected_day is not None and p.expected_day > today:
        text += f" It's now due {day_words(p.expected_day, today)}."
    return text


def due(p: Parcel) -> str:
    """One parcel due today."""
    if p.signature:
        return f"A delivery from {p.shop} is due today and needs someone to sign for it."
    if when := window(p):
        return f"A delivery from {p.shop} is due {when}."
    return f"A delivery from {p.shop} is due today."


def came(p: Parcel, tz: ZoneInfo) -> str:
    """One parcel that came today: when and where, when its carrier said."""
    if p.source == "lookup" and p.delivered_at is not None:
        at = p.delivered_at.astimezone(tz)
        text = f"A delivery from {p.shop} came at {clock(f'{at:%H:%M}')}."
        where = p.left_at.lower()
        return text + (f" It was left at the {where}." if where else " It may be at the door.")
    return f"A delivery from {p.shop} came today. It may be at the door."


def moved(p: Parcel, today: date) -> str:
    assert p.expected_day is not None
    return f"The delivery from {p.shop} is now due {day_words(p.expected_day, today)}."


def why(p: Parcel, what: str) -> str:
    """Where the news came from: "UPS's tracking says so." """
    if p.source == "lookup":
        return f"{carrier_name(p)}'s tracking says so."
    return f"A shipping email says {what}."


def several(parcels: list[Parcel], verb: str) -> str:
    """ "Two deliveries from Amazon are due today.", "Deliveries from Amazon and Chewy came
    today." """
    shops = list(dict.fromkeys(p.shop for p in parcels))
    if len(shops) == 1:
        what = f"{count_word(len(parcels))} deliveries from {shops[0]}"
    else:
        what = f"Deliveries from {and_list(shops)}"
    return f"{what} {verb}"


def describe(p: Parcel, today: date, tz: ZoneInfo) -> str:
    """One parcel, in a sentence, for chat."""
    if p.status == "problem":
        return problem(p, today)
    if p.status == "delivered":
        day = p.expected_day or today
        if day == today:
            return came(p, tz)
        when = "yesterday" if day == today - timedelta(days=1) else f"on {day:%A}"
        return f"The delivery from {p.shop} came {when}."
    if p.expected_day == today:
        return due(p)
    if p.expected_day is not None:
        text = f"The delivery from {p.shop} is due {day_words(p.expected_day, today)}."
        return text if p.expected_day > today else text.replace("is due", "was due")
    return f"The delivery from {p.shop} is on its way; no one has said when it's due."


def morning(parcels: list[Parcel], today: date) -> str | None:
    """The morning message's line: what's due today, then any problems."""
    coming = [
        p
        for p in parcels
        if p.expected_day == today and p.status in ("on_the_way", "out_for_delivery")
    ]
    troubles = [p for p in parcels if p.status == "problem"]
    parts: list[str] = []
    if coming:
        shops = and_list(list(dict.fromkeys(p.shop for p in coming)))
        head = (
            "A delivery today"
            if len(coming) == 1
            else f"{count_word(len(coming))} deliveries today"
        )
        windows = [(p.shop, window(p)) for p in coming if window(p)]
        if len(coming) == 1 and windows:
            tail = f" ({windows[0][1]})"
        elif windows:
            tail = " (" + "; ".join(f"{shop} {when}" for shop, when in windows) + ")"
        else:
            tail = ""
        parts.append(f"{head}, from {shops}{tail}.")
    parts += [problem(p, today) for p in troubles[:2]]
    return " ".join(parts) or None


# ----- chat (PT6a) ----------------------------------------------------------------------------


@tool(
    "parcel_status",
    "Say how this person's parcels are doing (from their shipping emails and the carriers): "
    "due when, delivered, or a problem. Use for 'where's my order?' or 'did the Chewy box "
    "come?'. Only the shop's name is known, never what's in a parcel.",
    {
        "shop": {
            "type": "string",
            "description": "The shop or sender asked about ('Chewy'); empty for every parcel.",
        }
    },
)
async def parcel_status(ctx: ToolContext, args: dict[str, Any]) -> str:
    deliveries = ctx.services.maybe(keys.deliveries)
    if deliveries is None:
        return "Email isn't set up on this server, so Themi doesn't know of any parcels."
    tz = deliveries.tz()
    today = clock_now().astimezone(tz).date()
    shop = " ".join(str(args.get("shop") or "").casefold().split())
    own = [p for p in deliveries.parcels() if p.member_id == ctx.member.id]
    recent = [
        p
        for p in own
        if p.status != "delivered" or (p.expected_day or today) >= today - timedelta(days=2)
    ]
    found = [p for p in recent if not shop or shop in p.shop.casefold()]
    if not found:
        if shop:
            return f"I haven't seen a shipping email from {args.get('shop')} lately."
        return "No parcels on their way that I know of."
    found.sort(key=lambda p: (p.expected_day or date.max, p.id))  # soonest first
    return "\n".join(describe(p, today, tz) for p in found)
