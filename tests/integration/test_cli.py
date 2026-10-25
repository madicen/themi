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


def test_keygen_prints_a_usable_key() -> None:
    from themi.storage.secrets import Cipher

    result = subprocess.run(
        [sys.executable, "-m", "themi", "keygen"], capture_output=True, text=True, check=True
    )
    key = result.stdout.strip()
    cipher = Cipher(key)
    assert cipher.decrypt(cipher.encrypt("ok")).reveal() == "ok"
