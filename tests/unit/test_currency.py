"""F50b (bug #232): amounts with their currency, and dollars at the day's rate."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from tests.fakes.rates import FakeRates
from tests.fixtures.family import SeededFamily
from themi.standard.currency import Converter, Money, about, find_money, in_dollars
from themi_google.expected import paid_amount, paid_money, parse_money

DAY = date(2026, 11, 19)


def read(text: str) -> list[tuple[str, str]]:
    return [(f"{f.money.value:.2f}", f.money.currency) for f in find_money(text)]


def test_an_amount_is_read_with_its_currency() -> None:
    assert read("We've collected your pledge of HK$ 816.00.") == [("816.00", "HKD")]
    assert read("CA$ 100.00 pledge") == [("100.00", "CAD")]
    assert read("Total: $1,112.40") == [("1112.40", "USD")]
    assert read("US$269") == [("269.00", "USD")]
    assert read("€400.00 and £12.50") == [("400.00", "EUR"), ("12.50", "GBP")]
    assert read("12,00 EUR") == [("12.00", "EUR")]
    assert read("EUR 12.00") == [("12.00", "EUR")]
    assert read("CHF 40") == [("40.00", "CHF")]
    assert read("No money here, 30 days") == []


def test_an_amount_is_written_back_as_people_write_it() -> None:
    assert Money(Decimal("816"), "HKD").words() == "HK$816.00"
    assert Money(Decimal("12.5"), "EUR").words() == "€12.50"
    assert Money(Decimal("40"), "CHF").words() == "CHF 40.00"
    assert about(10486) == "$105"


def test_the_models_amount_is_kept_only_in_the_currency_the_email_says() -> None:
    text = "We've collected your pledge of HK$ 816.00 for CeraDice."
    assert paid_money("HK$ 816.00", text) == Money(Decimal("816"), "HKD")
    assert paid_amount("HK$ 816.00", text) is None  # not dollars
    assert paid_money("$816.00", "Charged $816.00 today") == Money(Decimal("816"), "USD")
    assert paid_money("HK$ 816.00", "Charged $816.00 today") is None  # a different currency
    assert parse_money("Your pledge: HK$ 816.00. HK$ 336,444 pledged so far.") == Money(
        Decimal("816"), "HKD"
    )


async def test_a_days_rate_is_asked_once(family: SeededFamily) -> None:
    rates = FakeRates()
    rates.set("HKD", 0.1285)
    converter = Converter(family.db, rates.client())
    pledge = Money(Decimal("816.00"), "HKD")
    assert await converter.to_dollars(pledge, DAY) == 10486
    assert await converter.to_dollars(Money(Decimal("100"), "HKD"), DAY) == 1285
    assert rates.count() == 1
    assert await converter.to_dollars(Money(Decimal("5"), "USD"), DAY) == 500
    assert rates.count() == 1


async def test_without_a_rate_theres_no_amount(family: SeededFamily) -> None:
    rates = FakeRates()
    rates.fail = True
    converter = Converter(family.db, rates.client())
    assert await converter.to_dollars(Money(Decimal("816"), "HKD"), DAY) is None
    rates.fail = False  # a currency it doesn't have
    assert await converter.to_dollars(Money(Decimal("10"), "TWD"), DAY) is None
    assert family.db.scalar("SELECT COUNT(*) FROM exchange_rates") == 0


async def test_a_receipts_total_written_only_in_another_currency_is_converted(
    family: SeededFamily,
) -> None:
    rates = FakeRates()
    rates.set("CAD", 0.72)
    converter = Converter(family.db, rates.client())
    receipt = "Thanks for your order! Total: CA$ 25.00"
    assert await in_dollars(converter, 2500, receipt, DAY) == 1800
    assert await in_dollars(converter, 2500, "Total: $25.00", DAY) == 2500
    assert await in_dollars(converter, 2500, "Order total 25.00", DAY) == 2500  # no sign
    assert await in_dollars(None, 2500, receipt, DAY) is None  # no rate: left out
    rates.fail = True
    assert await in_dollars(Converter(family.db, rates.client()), 900, "€9.00", DAY) is None
