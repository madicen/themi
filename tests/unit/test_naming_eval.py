"""P8a: the offline "which task?" eval. A check is scored on fake cases, and today's word
check holds its baseline on the real ones."""

from __future__ import annotations

from tests.evals.naming import (
    KINDS,
    NamingCase,
    Totals,
    format_naming,
    load_naming_cases,
    score,
    totals,
    word_check,
)

# The word check on tests/evals/naming_cases.json, 2026-11-03 (P8a's Notes).
BASELINE = (45, 19, 9, 18)  # cases, right, wrongly refused, wrongly accepted


def case(id: str, message: str, means: tuple[str, ...], *, before: str = "") -> NamingCase:
    tasks = ("Go for a run", "Bring bins in", "Contact Sam's parents about babysitting")
    return NamingCase(id, "plain", message, before, "", tasks, means)


CASES = [
    case("words", "I went for a run", ("Go for a run",)),
    case("paraphrase", "did my 5k", ("Go for a run",)),
    case("pair", "We contacted Sam's parents", ("Contact Sam's parents about babysitting",)),
    case("nothing", "Ran the dishwasher", ()),
]


def test_a_perfect_check_gets_every_case_right() -> None:
    scored = score(CASES, lambda c, tried: tried in c.means)
    assert totals(scored) == Totals(cases=4, right=4, wrongly_refused=0, wrongly_accepted=0)


def test_the_word_check_is_scored_both_ways() -> None:
    scored = {s.case.id: s for s in score(CASES, word_check)}
    assert scored["words"].right
    assert scored["paraphrase"].wrongly_refused == ("Go for a run",)
    assert scored["pair"].right  # the bins stay refused
    assert scored["nothing"].wrongly_accepted == ("Go for a run",)  # "ran" is "run"
    table = format_naming(list(scored.values()))
    assert "paraphrase: 'did my 5k' refused Go for a run" in table
    assert "nothing: 'Ran the dishwasher' accepted Go for a run" in table


def test_a_short_answer_is_read_with_themis_question() -> None:
    yes = case(
        "yes",
        "Yes please",
        ("Contact Sam's parents about babysitting",),
        before='Should I move "Contact Sam\'s parents about babysitting" to 6 pm?',
    )
    assert score([yes], word_check)[0].right


def test_the_case_file_is_sound_and_holds_the_baseline() -> None:
    cases = load_naming_cases()
    assert len({c.id for c in cases}) == len(cases)
    for c in cases:
        assert c.kind in KINDS
        assert set(c.means) <= set(c.tasks), c.id
    t = totals(score(cases, word_check))
    cases_, right, refused, accepted = BASELINE
    assert t.cases == cases_
    assert t.right >= right and t.wrongly_refused <= refused and t.wrongly_accepted <= accepted
