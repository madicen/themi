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


def _env(tmp_path) -> dict[str, str]:
    import os

    from themi.storage.secrets import generate_key

    return {
        **os.environ,
        "THEMI_SECRET_KEY": generate_key(),
        "THEMI_DB_PATH": str(tmp_path / "themi.db"),
    }


def test_init_then_invite_end_to_end(tmp_path) -> None:
    env = _env(tmp_path)
    run = {"capture_output": True, "text": True, "env": env, "cwd": tmp_path}

    init = subprocess.run(
        [sys.executable, "-m", "themi", "init"],
        input="The Household\nAmerica/Chicago\n120\nErin\n",
        check=True,
        **run,
    )
    assert "Invite code for Erin:" in init.stdout and "/start " in init.stdout

    invite = subprocess.run([sys.executable, "-m", "themi", "invite", "Husband"], check=True, **run)
    assert "Invite code for Husband:" in invite.stdout

    again = subprocess.run(
        [sys.executable, "-m", "themi", "init"], input="x\nUTC\n0\nY\n", check=False, **run
    )
    assert again.returncode == 1
    assert "already has a family" in again.stderr


def test_missing_secret_key_gives_a_clear_error(tmp_path) -> None:
    env = _env(tmp_path)
    del env["THEMI_SECRET_KEY"]
    result = subprocess.run(
        [sys.executable, "-m", "themi", "invite", "Husband"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 1
    assert "THEMI_SECRET_KEY" in result.stderr and "Traceback" not in result.stderr


def test_run_requires_a_telegram_token(tmp_path) -> None:
    env = _env(tmp_path)
    env.pop("TELEGRAM_BOT_TOKEN", None)
    env.pop("THEMI_DISABLE_TELEGRAM", None)
    result = subprocess.run(
        [sys.executable, "-m", "themi", "run"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 1
    assert "TELEGRAM_BOT_TOKEN" in result.stderr and "Traceback" not in result.stderr
