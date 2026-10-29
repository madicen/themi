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
