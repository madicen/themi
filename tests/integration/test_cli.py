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


def test_login_link_prints_a_working_url(tmp_path) -> None:
    env = _env(tmp_path)
    run = {"capture_output": True, "text": True, "env": env, "cwd": tmp_path}
    subprocess.run(
        [sys.executable, "-m", "themi", "init"],
        input="Household\nUTC\n0\nErin\n",
        check=True,
        **run,
    )
    result = subprocess.run(
        [sys.executable, "-m", "themi", "login-link", "Erin"], check=True, **run
    )
    url = result.stdout.strip()
    assert url.startswith("http://127.0.0.1:8080/login/")
    missing = subprocess.run(
        [sys.executable, "-m", "themi", "login-link", "Nobody"], check=False, **run
    )
    assert missing.returncode == 1 and "no member called Nobody" in missing.stderr


def test_invite_prints_a_tap_to_start_link_for_the_bot(tmp_path, fake_telegram) -> None:
    from tests.fakes.telegram_api import BOT_TOKEN, BOT_USER

    env = {**_env(tmp_path), "TELEGRAM_BOT_TOKEN": BOT_TOKEN}
    run = {"capture_output": True, "text": True, "cwd": tmp_path}
    subprocess.run(
        [sys.executable, "-m", "themi", "init"],
        input="The Household\nAmerica/Chicago\n0\nErin\n",
        check=True,
        env={**env, "TELEGRAM_API_URL": fake_telegram.base_url.removesuffix("/bot")},
        **run,
    )
    linked = subprocess.run(
        [sys.executable, "-m", "themi", "invite", "Husband"],
        check=True,
        env={**env, "TELEGRAM_API_URL": fake_telegram.base_url.removesuffix("/bot")},
        **run,
    )
    code = linked.stdout.split("Invite code for Husband: ")[1].split()[0]
    assert f"https://t.me/{BOT_USER['username']}?start={code}" in linked.stdout
    assert BOT_TOKEN not in linked.stdout + linked.stderr

    # Telegram unreachable: the code still prints, just without the link.
    offline = subprocess.run(
        [sys.executable, "-m", "themi", "invite", "Husband"],
        check=True,
        env={**env, "TELEGRAM_API_URL": "http://127.0.0.1:9"},
        **run,
    )
    assert "Invite code for Husband:" in offline.stdout and "t.me" not in offline.stdout


def test_feedback_prints_new_reports_and_marks_them_done(tmp_path) -> None:
    import json
    import sqlite3

    env = _env(tmp_path)
    run = {"capture_output": True, "text": True, "env": env, "cwd": tmp_path}
    subprocess.run(
        [sys.executable, "-m", "themi", "init"],
        input="The Household\nAmerica/Chicago\n0\nErin\n",
        check=True,
        **run,
    )
    empty = subprocess.run([sys.executable, "-m", "themi", "feedback"], check=True, **run)
    assert empty.stdout == "No new feedback.\n"

    db = sqlite3.connect(tmp_path / "themi.db")
    context = json.dumps({"member": {"name": "Erin"}, "local_time": "Sun 25 Oct 2026 14:00 CDT"})
    db.execute(
        "INSERT INTO feedback (member_id, kind, text, context, created_at) "
        "VALUES (1, 'bug', 'the list was wrong', ?, '2026-10-25T19:00:00+00:00')",
        (context,),
    )
    db.commit()
    db.close()

    report = subprocess.run([sys.executable, "-m", "themi", "feedback"], check=True, **run)
    assert "## Bug #1 from Erin, Sun 25 Oct 2026 14:00 CDT" in report.stdout
    assert "> the list was wrong" in report.stdout

    done = subprocess.run(
        [sys.executable, "-m", "themi", "feedback", "--done", "1"], check=True, **run
    )
    assert done.stdout.strip() == "Marked 1 of 1 as reviewed."
    after = subprocess.run([sys.executable, "-m", "themi", "feedback"], check=True, **run)
    assert after.stdout == "No new feedback.\n"
    every = subprocess.run([sys.executable, "-m", "themi", "feedback", "--all"], check=True, **run)
    assert "## Bug #1 from Erin, Sun 25 Oct 2026 14:00 CDT (reviewed)" in every.stdout
