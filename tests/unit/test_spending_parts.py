from datetime import date

import pytest

from themi.core.spending import money, month_of
from themi.core.tools import ToolFailed


def test_money_reads_as_dollars() -> None:
    assert money(5197) == "$51.97"
    assert money(123456) == "$1,234.56"


def test_a_month_is_its_first_day() -> None:
    assert month_of("", date(2026, 10, 28)) == date(2026, 10, 1)
    assert month_of("2026-09", date(2026, 10, 28)) == date(2026, 9, 1)
    with pytest.raises(ToolFailed):
        month_of("September", date(2026, 10, 28))
