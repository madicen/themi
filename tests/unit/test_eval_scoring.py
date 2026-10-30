import json
from pathlib import Path

from tests.evals.compare import arm, compare, flips, verdict
from tests.evals.rescore import load_run, rescore
from tests.evals.scoring import Case, format_summary, load_cases, score, summarise


def case(**fields) -> Case:
    return Case(**{"id": "c", "category": "pantry", "message": "m", **fields})


def test_the_dataset_is_big_enough_and_well_formed() -> None:
    cases = load_cases()
    assert len(cases) >= 40
    assert len({c.id for c in cases}) == len(cases)
    categories = {c.category for c in cases}
    for wanted in (
        "energy_notes",
        "pantry",
        "rules",
        "context_repair",
        "approvals",
        "relays",
        "small_talk",
    ):
        assert wanted in categories
    assert all(c.speaker in ("Erin", "Husband") for c in cases)


def test_expected_calls_and_arguments() -> None:
    c = case(expect=("update_pantry",), args={"update_pantry": {"_json": ["olive oil", "out"]}})
    good = score(
        c, [("update_pantry", {"items": [{"name": "olive oil", "status": "out"}]})], ["Noted."], 2
    )
    assert good.passed
    wrong = score(
        c, [("update_pantry", {"items": [{"name": "olive oil", "status": "low"}]})], ["Noted."], 2
    )
    assert wrong.problems == ["update_pantry arguments don't mention out"]
    assert score(c, [], ["Noted."], 2).problems == ["expected a update_pantry call"]


def test_unexpected_and_allowed_extra_calls() -> None:
    c = case(expect=(), allow=("list_open_items",))
    assert score(c, [("list_open_items", {})], ["Nothing waiting."], 2).passed
    assert score(c, [("create_task", {})], ["Done."], 2).problems == ["unexpected create_task call"]


def test_numeric_argument_rules() -> None:
    c = case(expect=("log_energy_note",), args={"log_energy_note": {"effect": {"lt": 0}}})
    assert score(c, [("log_energy_note", {"effect": -1})], ["Oof."], 2).passed
    assert not score(c, [("log_energy_note", {"effect": 2})], ["Oof."], 2).tools_ok
    # energy-plumber: Gemini sends "-3"; the tools read it as -3, so the score does too.
    assert score(c, [("log_energy_note", {"effect": "-3"})], ["Oof."], 2).passed
    assert not score(c, [("log_energy_note", {"effect": "lots"})], ["Oof."], 2).tools_ok


def test_replies_are_checked_for_pda_and_scores_but_quotes_are_exempt() -> None:
    c = case()
    assert score(c, [], ["Whenever suits you."], 3).passed
    assert not score(c, [], ["You must do this now."], 3).pda_ok
    assert not score(c, [], ["You're at 40% today."], 3).pda_ok
    assert score(c, [], ["A draft:\n> You must call me back."], 3).pda_ok
    assert not score(c, [], [], 3).tools_ok  # no reply at all


def test_summary_by_category() -> None:
    outcomes = [
        score(case(category="pantry"), [], ["ok"], 2),
        score(case(category="pantry"), [], ["You must."], 3),
        score(case(category="rules"), [], ["ok"], 2),
    ]
    summary = summarise(outcomes)
    assert summary["categories"]["pantry"] == {"cases": 2, "passed": 1, "tools": 2, "pda": 1}
    assert summary["pass_rate"] == 66.7
    assert "pantry" in format_summary("gemini", summary)


def test_a_case_the_ai_never_answered_is_unavailable_not_passed() -> None:
    from themi.core.agent import BUSY_TEXT

    outcome = score(case(expect=()), [], [BUSY_TEXT], 2)
    assert outcome.unavailable and not outcome.passed
    assert outcome.problems == ["no AI backend answered (quota, outage or rate limit)"]
    summary = summarise([outcome, score(case(category="rules"), [], ["ok"], 2)])
    assert summary["unavailable"] == 1
    assert summary["cases"] == 1 and summary["pass_rate"] == 100.0  # only answered cases count
    assert "pantry" not in summary["categories"]
    assert "1 couldn't run" in format_summary("gemini", summary)


def test_read_only_lookups_are_always_allowed() -> None:
    c = case(expect=("create_task",))
    calls = [("list_open_items", {}), ("show_pantry", {}), ("create_task", {})]
    assert score(c, calls, ["On it."], 2).passed


def test_either_of_two_tools_can_satisfy_a_case() -> None:
    c = case(expect_any=("remember_fact", "propose_rule"))
    assert score(c, [("propose_rule", {})], ["Noted."], 2).passed
    assert score(c, [("remember_fact", {})], ["Noted."], 2).passed
    assert score(c, [], ["Noted."], 2).problems == ["expected one of remember_fact, propose_rule"]
    assert score(c, [("create_task", {})], ["Noted."], 2).problems == [
        "expected one of remember_fact, propose_rule",
        "unexpected create_task call",
    ]


def test_only_the_models_own_replies_are_scored() -> None:
    from tests.evals.scoring import model_replies

    sent = [
        ("approval", "Add eggs to the grocery list\nGo ahead, or not now?"),
        ("chat", "Asked about eggs."),
    ]
    assert model_replies(sent) == ["Asked about eggs."]
    # Saved runs from before kinds were recorded: approval cards are recognised by their ask.
    assert model_replies(["Add eggs\nGo ahead, or not now?", "Asked."]) == ["Asked."]


# ----- P5: repeats, timings, and comparing two runs ----------------------------------


def outcome(case_id: str, passed: bool, run: int = 1, seconds: float = 2.0, tools: int = 20):
    c = case(id=case_id, expect=("update_pantry",))
    o = score(c, [("update_pantry", {})] if passed else [], ["Noted."], 2)
    o.run, o.model_seconds, o.tools_sent, o.tools_chars = run, [seconds], tools, tools * 500
    return o


def test_repeats_tell_flaky_cases_from_failing_ones() -> None:
    runs = [
        outcome("steady", True, 1),
        outcome("steady", True, 2),
        outcome("wobbly", True, 1),
        outcome("wobbly", False, 2),
        outcome("broken", False, 1),
        outcome("broken", False, 2),
    ]
    summary = summarise(runs)
    assert summary["runs"] == 2 and summary["passed"] == 3 and summary["cases"] == 6
    assert summary["flaky"] == ["wobbly"] and summary["failing"] == ["broken"]
    text = format_summary("gemini", summary)
    assert "Each case ran 2 times" in text and "Flaky (passed some runs): wobbly" in text
    assert "Failed every run: broken" in text


def test_timings_are_summarised_as_medians() -> None:
    summary = summarise([outcome("a", True, seconds=1.0), outcome("b", True, seconds=5.0)])
    assert summary["median_seconds"] == 3.0 and summary["median_calls"] == 1
    assert summary["median_tools_sent"] == 20
    assert "3.0 s in model calls, 1 calls, 20 tools sent" in format_summary("g", summary)


def test_a_run_without_timings_still_summarises() -> None:
    # Saved runs from before P5 have no timings.
    o = outcome("old", True)
    o.model_seconds = []
    assert summarise([o])["median_calls"] == 0
    assert "Per case" not in format_summary("g", summarise([o]))


def test_rescore_reads_repeats_and_timings_back(tmp_path: Path) -> None:
    path = tmp_path / "gemini-all-1.json"
    item = {
        "id": "pantry-olive-oil",
        "calls": [["update_pantry", {"items": [{"name": "olive oil", "status": "out"}]}]],
        "replies": ["Noted, olive oil is out."],
        "sent": [["chat", "Noted, olive oil is out."]],
        "run": 2,
        "model_seconds": [1.5, 0.5],
        "tools_sent": 31,
        "tools_chars": 20000,
    }
    path.write_text(json.dumps({"provider": "gemini", "routing": "all", "cases": [item]}))
    details, (o,) = load_run(path)
    assert details == {"provider": "gemini", "routing": "all"}
    assert (o.run, o.model_seconds, o.tools_sent, o.tools_chars) == (2, [1.5, 0.5], 31, 20000)
    assert "gemini, all tools (re-scored)" in rescore(path)


def test_compare_lists_real_differences_and_applies_the_rule() -> None:
    groups = arm(
        "groups",
        [outcome("a", True, r) for r in (1, 2)]
        + [outcome("b", False, r) for r in (1, 2)]
        + [outcome("c", True, 1), outcome("c", False, 2)],
    )
    every = arm(
        "all",
        [outcome("a", True, r, seconds=2.2) for r in (1, 2)]
        + [outcome("b", True, r, seconds=2.2) for r in (1, 2)]
        + [outcome("c", True, r, seconds=2.2) for r in (1, 2)],
    )
    assert flips(groups, every) == ([], ["b"])
    assert verdict(groups, every) == (True, [])
    text = compare(groups, every)
    assert "Always failed, now always passes: b" in text
    assert "  c: 1/2 -> 2/2" in text and "all wins" in text


def test_compare_keeps_groups_when_all_loses_a_case_or_is_slow() -> None:
    groups = arm("groups", [outcome("a", True, r) for r in (1, 2)])
    worse = arm("all", [outcome("a", False, r) for r in (1, 2)])
    wins, reasons = verdict(groups, worse)
    assert not wins and any("always fails: a" in r for r in reasons)
    slow = arm("all", [outcome("a", True, r, seconds=2.5) for r in (1, 2)])
    wins, reasons = verdict(groups, slow)
    assert not wins and reasons == ["median 2.5 s against 2.0 s: more than 20% slower"]
    assert "groups stays" in compare(groups, slow)


def test_compare_allows_one_case_of_noise() -> None:
    groups = arm("groups", [outcome(x, True) for x in "abcd"])
    every = arm("all", [outcome("a", False), *(outcome(x, True) for x in "bcd")])
    # One case lost on a single run: within one case, though it's also an always/never flip.
    assert every.passed_cases == groups.passed_cases - 1
    assert verdict(groups, every)[1] == ["always passed, now always fails: a"]
