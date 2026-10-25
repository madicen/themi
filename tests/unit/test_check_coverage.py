from tools.check_coverage import check


def report(overall: float, **files: tuple[int, int]) -> dict:
    return {
        "totals": {"percent_covered": overall},
        "files": {
            name: {"summary": {"covered_lines": c, "num_statements": n}}
            for name, (c, n) in files.items()
        },
    }


GOOD = {
    "src/themi/ai/router.py": (95, 100),
    "src/themi/channels/outbox.py": (90, 100),
    "src/themi/channels/pda.py": (100, 100),
    "src/themi/autonomy/engine.py": (99, 100),
    "src/themi/energy/model.py": (91, 100),
}


def test_all_gates_pass() -> None:
    assert check(report(80.0, **GOOD)) == []


def test_a_low_package_or_overall_fails() -> None:
    files = {**GOOD, "src/themi/energy/model.py": (89, 100)}
    assert check(report(74.0, **files)) == ["overall 74.0% < 75%", "themi.energy 89.0% < 90%"]


def test_missing_data_is_a_failure_not_a_pass() -> None:
    files = {k: v for k, v in GOOD.items() if "pda" not in k}
    assert check(report(80.0, **files)) == [
        "themi.channels.pda: no coverage data (is src/themi/channels/pda.py measured?)"
    ]
