"""CM1c: the sidecar eval's scoring (no model)."""

from __future__ import annotations

from tests.evals.sidecar import SidecarCase, load, score, summary


def case(expect: tuple[dict, ...] = (), **kw: object) -> SidecarCase:
    return SidecarCase("c", "task", "Erin", "msg", "reply", expect, **kw)  # type: ignore[arg-type]


def test_the_cases_load_and_cover_every_kind() -> None:
    cases = load()
    assert len({c.id for c in cases}) == len(cases)
    assert {c.kind for c in cases} >= {"none", "task", "update", "event", "fact", "mode"}
    assert sum(c.kind == "none" for c in cases) >= 8  # mostly things to leave alone


def test_a_meant_task_made_is_a_hit() -> None:
    scored = score(case(({"tool": "create_task", "words": ["vet"]},)), [
        ("create_task", {"title": "Call the vet"})
    ], {})  # fmt: skip
    assert scored.passed and scored.hits == ["create_task"]


def test_wrong_words_are_a_miss_and_an_extra() -> None:
    scored = score(case(({"tool": "create_task", "words": ["vet"]},)), [
        ("create_task", {"title": "Clean the garage"})
    ], {})  # fmt: skip
    assert scored.misses == ["create_task"] and scored.extras == ["create_task"]


def test_an_update_must_name_the_right_task() -> None:
    want = ({"tool": "complete_task", "task": "Call the vet"},)
    assert score(case(want), [("complete_task", {"task_id": 4})], {"Call the vet": 4}).passed
    assert not score(case(want), [("complete_task", {"task_id": 5})], {"Call the vet": 4}).passed


def test_precision_and_recall_per_kind() -> None:
    results = [
        score(case(({"tool": "create_task"},)), [("create_task", {})], {}),
        score(case(), [("create_task", {})], {}),  # made when nothing was meant
        score(case(({"tool": "remember_fact"},)), [], {}),  # missed
    ]
    kinds = summary(results)
    assert kinds["task"]["precision"] == 0.5 and kinds["task"]["recall"] == 1.0
    assert kinds["fact"]["recall"] == 0.0 and kinds["fact"]["precision"] == 1.0
