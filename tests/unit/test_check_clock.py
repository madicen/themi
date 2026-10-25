from pathlib import Path

import pytest

from tools.check_clock import REPO_ROOT, find_violations, violations_in_source


@pytest.mark.parametrize(
    "source",
    [
        "from datetime import datetime\nx = datetime.now()",
        "import datetime\nx = datetime.datetime.now()",
        "from datetime import datetime, UTC\nx = datetime.now(UTC)",
        "from datetime import datetime\nx = datetime.utcnow()",
        "from datetime import date\nx = date.today()",
        "import time\nx = time.time()",
        "import time\nx = time.time_ns()",
    ],
)
def test_flags_direct_wall_clock_reads(source: str) -> None:
    assert violations_in_source(source)


@pytest.mark.parametrize(
    "source",
    [
        "from themi import clock\nx = clock.now()",
        "import time\nx = time.monotonic()",
        "from datetime import datetime\nx = datetime.fromisoformat('2026-01-01')",
        "x = obj.now",  # attribute access, not a call
    ],
)
def test_allows_clock_module_and_monotonic(source: str) -> None:
    assert violations_in_source(source) == []


def test_reports_file_and_line(tmp_path: Path) -> None:
    bad = tmp_path / "pkg" / "laundry.py"
    bad.parent.mkdir()
    bad.write_text("import time\n\n\ndef started():\n    return time.time()\n")
    problems = find_violations([tmp_path])
    assert len(problems) == 1
    assert f"{bad}:5" in problems[0]


def test_clock_module_itself_is_allowed() -> None:
    assert find_violations([REPO_ROOT / "src/themi/clock.py"]) == []


def test_codebase_is_clean() -> None:
    assert find_violations([REPO_ROOT / "src/themi"]) == []
