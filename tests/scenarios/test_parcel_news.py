"""PT6a: what the family reads about parcels: the wall's note, the morning message and chat.
Erin's inbox is linked and watched; Wednesday 21 October 2026, 9 am, Los Angeles (as in
WL8's scenario), unless a test moves the clock."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from html import unescape

from tests.scenarios.harness import Scenario
from tests.scenarios.test_wall_deliveries import get, mail  # noqa: F401  (the fixture)
from tests.scenarios.test_wall_deliveries import note as wall_note
from themi import clock
from themi.core import keys
from themi.core.tools import ToolContext
from themi.standard.day_summary import DaySummaryPreferences
from themi_google.deliveries import Deliveries, Fact
from themi_google.parcel_words import parcel_status

UPS = "1Z5R89390357567127"
USPS = "9400111206206406260787"


async def note(s: Scenario) -> str:
    return unescape(await wall_note(s))


def deliveries(s: Scenario) -> Deliveries:
    return s.app.services.get(keys.deliveries)


def today(s: Scenario) -> date:
    return s.today()


def record(s: Scenario, who: str = "Erin", **fact: object) -> None:
    fact.setdefault("at", clock.now())
    deliveries(s).record(s.member(who).id, Fact(**fact))  # type: ignore[arg-type]


async def test_a_problem_comes_first_in_the_carriers_words(mail: Scenario) -> None:  # noqa: F811
    record(mail, shop="Chewy", status="out_for_delivery", number=UPS, carriers=("ups",))
    record(
        mail,
        shop="Chewy",
        status="problem",
        number=UPS,
        carriers=("ups",),
        problem="The receiver was not available for delivery.",
        day=today(mail) + timedelta(days=1),
        source="lookup",
    )
    record(mail, shop="Amazon", status="delivered")  # came today: comes after the problem
    assert await note(mail) == "UPS couldn't deliver the parcel from Chewy. It's now due tomorrow."
    view = (await get(mail, "/wall/view/note")).text
    assert "UPS&#39;s tracking says so." in view and UPS not in view


async def test_a_lookup_says_when_and_where_it_came(mail: Scenario) -> None:  # noqa: F811
    came = datetime(2026, 10, 21, 20, 40, tzinfo=UTC)
    clock.advance(came - clock.now())
    record(
        mail,
        shop="Chewy",
        status="delivered",
        number=UPS,
        carriers=("ups",),
        source="lookup",
        delivered_at=came,
        left_at="Front Door",
    )
    assert (
        await note(mail) == "A delivery from Chewy came at 1:40 pm. It was left at the front door."
    )


async def test_a_window_and_a_signature(mail: Scenario) -> None:  # noqa: F811
    record(
        mail,
        shop="Chewy",
        status="out_for_delivery",
        number=UPS,
        carriers=("ups",),
        window_start="14:15",
        window_end="16:15",
        source="lookup",
    )
    assert await note(mail) == "A delivery from Chewy is due between 2:15 and 4:15 pm."
    record(
        mail,
        shop="Chewy",
        status="out_for_delivery",
        number=UPS,
        carriers=("ups",),
        window_start="14:15",
        window_end="16:15",
        signature=True,
        source="lookup",
        at=clock.now() + timedelta(minutes=1),
    )
    assert "needs someone to sign for it" in await note(mail)


async def test_a_parcel_moved_to_a_later_day(mail: Scenario) -> None:  # noqa: F811
    record(mail, shop="Chewy", status="on_the_way", number=UPS, carriers=("ups",), day=today(mail))
    record(
        mail,
        shop="Chewy",
        status="on_the_way",
        number=UPS,
        carriers=("ups",),
        day=today(mail) + timedelta(days=2),
        source="lookup",
        at=clock.now() + timedelta(minutes=1),
    )
    assert await note(mail) == "The delivery from Chewy is now due Friday."


# ----- the morning message ----------------------------------------------------------------


async def test_the_morning_message_has_their_own_parcels(mail: Scenario) -> None:  # noqa: F811
    erin = mail.member("Erin")
    mail.app.store.save_preferences(erin, erin.id, DaySummaryPreferences, morning_summary="07:15")
    thursday = date(2026, 10, 22)
    record(
        mail,
        shop="Chewy",
        status="on_the_way",
        number=UPS,
        carriers=("ups",),
        day=thursday,
        window_start="14:00",
        window_end="16:00",
    )
    record(mail, "Husband", shop="Etsy", status="on_the_way", day=thursday)  # his, not hers
    seven = datetime(2026, 10, 22, 14, 15, tzinfo=UTC)  # 7:15 am Thursday
    clock.advance(seven - clock.now())
    await mail.run_periodic("calendar.morning")
    sent = await mail.advance(minutes=45)
    [message] = [m for m in sent if m.startswith("Morning, Erin.")]
    assert message.endswith("\nA delivery today, from Chewy (between 2 and 4 pm).")
    assert "Etsy" not in message


# ----- chat -------------------------------------------------------------------------------


async def ask(s: Scenario, who: str, shop: str = "") -> str:
    return await parcel_status.handler(ToolContext(s.member(who), s.app.services), {"shop": shop})


async def test_chat_says_where_their_order_is(mail: Scenario) -> None:  # noqa: F811
    record(
        mail,
        shop="Chewy",
        status="on_the_way",
        number=UPS,
        carriers=("ups",),
        day=today(mail) + timedelta(days=2),
    )
    record(mail, shop="Chewy", status="out_for_delivery", number=USPS, carriers=("usps",))
    assert await ask(mail, "Erin", "chewy") == (
        "A delivery from Chewy is due today.\nThe delivery from Chewy is due Friday."
    )
    assert (
        await ask(mail, "Erin", "Zappos") == "I haven't seen a shipping email from Zappos lately."
    )
    assert await ask(mail, "Husband") == "No parcels on their way that I know of."  # Erin's
    assert UPS not in await ask(mail, "Erin")
