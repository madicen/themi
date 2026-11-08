from datetime import UTC, datetime, timedelta

import pytest

from themi.accounts import InvalidValue, sender_matches, sender_pattern
from themi.channels.pda import find_demands
from themi_google import expected
from themi_google.expected import (
    ExpectedEmail,
    cadence_words,
    dollars,
    paid_amount,
    parse_amount,
)

START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def pge(**changes) -> ExpectedEmail:
    fields = {
        "id": 1,
        "account_id": 1,
        "name": "the PG&E confirmation",
        "sender_pattern": "@pge.com",
        "subject_pattern": "payment confirmation",
        "cadence_days": 30,
        "grace_days": 3,
        "category": "email_mark_read",
        "known_senders": (),
        "last_seen_at": None,
        "last_alerted_at": None,
        "created_at": START,
    }
    return ExpectedEmail(**{**fields, **changes})


# ----- matching --------------------------------------------------------------------


def test_sender_patterns() -> None:
    assert sender_pattern(" PG&E.com ".replace("&", "")) == "@pge.com"
    assert sender_pattern("Billing@PGE.com") == "billing@pge.com"
    for bad in ("not an address", "@nodot", "a@@b.com"):
        with pytest.raises(InvalidValue):
            sender_pattern(bad)
    assert sender_matches("@pge.com", "billing@pge.com")
    assert sender_matches("@pge.com", "Billing@Mail.PGE.com")  # subdomains count
    assert not sender_matches("@pge.com", "billing@notpge.com")
    assert sender_matches("billing@pge.com", "BILLING@pge.com")


def test_an_expected_email_matches_sender_and_subject() -> None:
    item = pge()
    assert item.matches("billing@pge.com", "Your Payment Confirmation #42")
    assert not item.matches("billing@pge.com", "Outage in your area")
    assert not item.matches("billing@pgee.com", "Payment confirmation")
    assert pge(subject_pattern="").matches("anyone@pge.com", "Anything")


# ----- when it's overdue -----------------------------------------------------------


def test_missed_periods_start_after_cadence_and_grace() -> None:
    item = pge()
    assert item.missed_period(START + timedelta(days=32, hours=23)) is None
    first = START + timedelta(days=33)
    assert item.missed_period(first) == first
    assert item.missed_period(first + timedelta(days=29)) == first  # still the same period
    assert item.missed_period(first + timedelta(days=30)) == first + timedelta(days=30)

    seen = pge(last_seen_at=START + timedelta(days=40))
    assert seen.missed_period(START + timedelta(days=72)) is None  # counted from last seen
    assert seen.missed_period(START + timedelta(days=73)) == START + timedelta(days=73)


# ----- amounts ---------------------------------------------------------------------


def test_amounts_prefer_the_labelled_one() -> None:
    assert parse_amount("Thanks! We received your payment of $1,112.40 today.") == 111240
    assert parse_amount("Save $5 next time. Total charged: $84.20") == 8420
    # Bug #145: with no payment word, no amount (the largest was someone else's total).
    assert parse_amount("Credit limit $5,000. Statement $12.00 and $30") is None
    assert parse_amount("No money here, 30 days") is None
    assert dollars(111240) == "$1,112.40" and dollars(5) == "$0.05"


def test_cadence_words() -> None:
    assert [cadence_words(n) for n in (7, 30, 31, 90, 365, 45)] == [
        "week",
        "month",
        "month",
        "three months",
        "year",
        "45 days",
    ]


# ----- wording ---------------------------------------------------------------------


def test_anomaly_texts_pass_the_strictest_pda_check() -> None:
    label = "Mark confirmation emails as read"
    texts = [
        expected.OVERDUE_TEXT.format(
            name="The PG&E confirmation",
            address="erin@gmail.com",
            cadence="month",
            last="on September 3",
        ),
        expected.UNKNOWN_SENDER_TEXT.format(
            name="the PG&E confirmation", sender="x@pge.com", subject="Payment"
        ),
        expected.AMOUNT_TEXT.format(
            sender="PG&E", amount="$460.00", usual="$100.00", subject="Payment"
        ),
        expected.PAUSED_TEXT.format(label=label),
        expected.PAUSED_NOT_ADMIN_TEXT.format(label=label),
        expected.RESUMED_TEXT.format(label=label),
        expected.ALREADY_RESUMED_TEXT.format(label=label),
    ]
    for text in texts:
        assert find_demands(text, 3) == [], text


# Shaped like Kickstarter's emails (bug #145): other projects' totals come before "pledged".
FUNDED = (
    "Eldritch Pirate reached its goal!\n\nby Someone\n\n$336,444\n\npledged\n\n3,886\n\nbackers"
)
COLLECTED = (
    "**$2,000** goal\n\n$3,338 pledged\nYour pledge\nDetails\nCollector's Set \u2014 US$269\n\n"
    "$269.00\n\nShipping to United States\n\n$0.00\n\nPledge total\n****3271\n\n"
    "Expires 2/2028\n\n$269.00\n\nback another one today.\n\nHK$ 414,868\n------\n\npledged"
)
BACKED = "If it reaches its funding goal, your card will be charged $179.00 on November 1."


def test_a_projects_totals_are_not_what_the_reader_paid() -> None:
    assert parse_amount(FUNDED) is None
    assert parse_amount(COLLECTED) == 26900
    assert parse_amount(BACKED) == 17900
    assert parse_amount("Your pledge: $179.00. $5,000 pledged so far.") == 17900


def test_the_models_amount_is_kept_only_when_the_email_says_it() -> None:
    assert paid_amount("$179.00", BACKED) == 17900
    assert paid_amount("US$269", COLLECTED) == 26900
    assert paid_amount("$500.00", BACKED) is None  # not in the email: invented
    assert paid_amount("", BACKED) is None
    assert paid_amount("about forty dollars", BACKED) is None
