"""F34mb: pictures sent close together are kept together, in order (bug #184)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from themi import clock
from themi.channels.events import Picture
from themi.core.kept_pictures import MOST_TOGETHER, KeptPictures


def pic(n: int) -> Picture:
    return Picture(f"JPEG {n}".encode(), "image/jpeg")


@pytest.fixture(autouse=True)
def frozen(frozen_clock: datetime) -> None:
    del frozen_clock


def test_pictures_under_a_minute_apart_go_together_in_order() -> None:
    kept = KeptPictures()
    kept.keep(1, pic(1))
    clock.advance(timedelta(seconds=50))
    kept.keep(1, pic(2))
    clock.advance(timedelta(seconds=50))  # chained: each within a minute of the last
    kept.keep(1, pic(3))
    assert kept.group(1) == (pic(1), pic(2), pic(3))
    assert kept.peek(1) == pic(3)


def test_a_picture_later_starts_a_new_group_and_remembers_the_old() -> None:
    kept = KeptPictures()
    kept.keep(1, pic(1))
    clock.advance(timedelta(minutes=2))
    kept.keep(1, pic(2))
    assert kept.group(1) == (pic(2),)
    assert kept.before(1) == (pic(1),)
    clock.advance(timedelta(minutes=31))
    assert kept.before(1) == ()


def test_at_most_four_are_kept_together() -> None:
    kept = KeptPictures()
    kept.keep(1, *(pic(n) for n in range(6)))
    assert kept.group(1) == tuple(pic(n) for n in range(6 - MOST_TOGETHER, 6))


def test_an_album_joins_even_after_a_minute_and_says_so() -> None:
    kept = KeptPictures()
    assert kept.keep(1, pic(1), album="a") is False
    clock.advance(timedelta(minutes=2))
    assert kept.keep(1, pic(2), album="a") is True
    assert kept.group(1) == (pic(1), pic(2))


def test_each_member_has_their_own() -> None:
    kept = KeptPictures()
    kept.keep(1, pic(1))
    kept.keep(2, pic(2))
    assert kept.group(1) == (pic(1),) and kept.group(2) == (pic(2),)


def test_using_the_group_counts_its_turns() -> None:
    kept = KeptPictures()
    kept.keep(1, pic(1), pic(2))
    assert kept.use(1) == (pic(1), pic(2))
    assert kept.use(1) == (pic(1), pic(2))
    assert kept.use(1) == ()
