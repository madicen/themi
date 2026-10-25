import subprocess
import sys

from themi import __version__


def test_cli_reports_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "themi", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"themi {__version__}"
