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


def test_forwarding_an_email_reaches_the_email_tools() -> None:
    """F31d (idea #168): "Can you forward that email to Erin?" got "I can't forward emails"."""
    from tests.fakes.groups import choose_groups

    for said in (
        "Can you forward that email to Erin?",
        "forward that to Erin",
        "send this email to jenn@example.com",
    ):
        assert "email" in choose_groups([said]), said
