"""P7b: a message with two asks is embedded whole and clause by clause."""

from themi.core.routing import pieces


def test_two_asks_are_split_into_clauses() -> None:
    assert pieces(["Need a nap, then what's for dinner?"]) == [
        "Need a nap, then what's for dinner?",
        "Need a nap",
        "then what's for dinner",
    ]


def test_one_clause_and_short_bits_stay_whole() -> None:
    assert pieces(["Out of milk", "ok, thanks"]) == ["Out of milk", "ok, thanks"]
    assert pieces(["  ", "Out of milk", "Out of milk"]) == ["Out of milk"]
