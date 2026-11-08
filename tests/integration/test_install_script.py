"""SP8b: `deploy/install.sh` (themi install) against stand-in commands: no Docker, no
Tailscale, no sudo, no network. Each stand-in records what it was asked."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "install.sh"

STUBS = {
    "uname": 'case "$1" in -s) echo "${FAKE_OS:-Linux}" ;; -m) echo x86_64 ;; esac',
    "id": 'case "$1" in -u) echo 1000 ;; -un) echo themi ;; -nG) echo "themi docker" ;; esac',
    "hostname": "echo 192.168.1.20",
    "sleep": "exit 0",
    "python3": 'exec "$REAL_PYTHON" "$@"',
    "curl": """
for arg in "$@"; do
  case "$arg" in
    *health*) exit 0 ;;
    *get.docker.com*|*tailscale.com/install.sh*) echo 'true'; exit 0 ;;
  esac
done
exit 0""",
    "sudo": """
echo "sudo $*" >>"$FAKE_LOG"
case "$1" in
  docker|tailscale) exec "$@" ;;
  tee) cat >/dev/null ;;
esac
exit 0""",
    "docker": """
echo "docker $*" >>"$FAKE_LOG"
case "$*" in
  info) exit 0 ;;
  "compose pull") exit "${FAKE_PULL:-0}" ;;
  "compose exec -T themi cat /data/claim-code") echo "${FAKE_CODE:-}" ;;
esac
exit 0""",
    "tailscale": """
echo "tailscale $*" >>"$FAKE_LOG"
case "$*" in
  "status --json") echo '{"Self": {"DNSName": "themi.tail1234.ts.net."}}' ;;
esac
exit 0""",
}


class Host:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        self.home = root / "home" / "themi"
        self.log = root / "calls.log"
        self.log.write_text("")
        for name, body in STUBS.items():
            path = self.bin / name
            path.write_text("#!/bin/bash\n" + body.strip() + "\n")
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.source = root / "download"  # the script with the files beside it
        self.source.mkdir()
        for name in ("install.sh", "compose.yml", "update.sh", "control.sh", "themi-control.path",
                     "themi-control.service", "themi-control-check.service",
                     "themi-control-check.timer"):  # fmt: skip
            shutil.copy(REPO / "deploy" / name, self.source / name)

    def run(self, **env: str) -> subprocess.CompletedProcess[str]:
        bash = shutil.which("bash") or "/bin/bash"
        full = {
            "PATH": f"{self.bin}{os.pathsep}/usr/bin:/bin",
            "HOME": str(self.root / "home"),
            "THEMI_HOME": str(self.home),
            "THEMI_NONINTERACTIVE": "1",
            "THEMI_NO_RUNNER": "1",
            "THEMI_FUNNEL": "no",
            "FAKE_LOG": str(self.log),
            "REAL_PYTHON": shutil.which("python3") or "python3",
            **env,
        }
        return subprocess.run(
            [bash, str(self.source / "install.sh")],
            env=full,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()

    def env_file(self) -> str:
        return (self.home / ".env").read_text()


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def test_it_is_shellcheck_clean() -> None:
    shellcheck = shutil.which("shellcheck") or str(Path(sys.executable).parent / "shellcheck")
    if not Path(shellcheck).exists():
        pytest.skip("shellcheck isn't installed (pip install shellcheck-py)")
    found = subprocess.run(
        [shellcheck, "-S", "warning", str(SCRIPT)], capture_output=True, text=True
    )
    assert found.returncode == 0, found.stdout


def test_a_fresh_install_starts_themi_and_says_the_claim_code(host: Host) -> None:
    done = host.run(FAKE_CODE="ABCD-EFGH")
    assert done.returncode == 0, done.stderr + done.stdout
    assert (host.home / "compose.yml").read_text() == (REPO / "deploy/compose.yml").read_text()
    env = host.env_file()
    assert "THEMI_IMAGE=ghcr.io/madicen/themi" in env and "THEMI_VERSION=latest" in env
    assert stat.S_IMODE((host.home / ".env").stat().st_mode) == 0o600
    calls = host.calls()
    assert calls.index("docker compose pull") < calls.index("docker compose up -d")
    assert "enter this claim code to set Themi up: ABCD-EFGH" in done.stdout
    assert "Themi's website: http://192.168.1.20:8080" in done.stdout


def test_running_it_again_changes_nothing(host: Host) -> None:
    assert host.run(FAKE_CODE="ABCD-EFGH").returncode == 0
    before = host.env_file()
    files = {p.name: p.read_text() for p in host.home.iterdir() if p.is_file()}
    again = host.run(FAKE_CODE="")
    assert again.returncode == 0, again.stderr
    assert host.env_file() == before
    assert {p.name: p.read_text() for p in host.home.iterdir() if p.is_file()} == files
    assert ".env is there already" in again.stdout
    assert "This Themi is set up already" in again.stdout


def test_an_env_already_there_is_kept_and_only_added_to(host: Host) -> None:
    host.home.mkdir(parents=True)
    (host.home / ".env").write_text("THEMI_SECRET_KEY=keep-me\nTHEMI_VERSION=1.2.0\n")
    assert host.run().returncode == 0
    env = host.env_file()
    assert env.startswith("THEMI_SECRET_KEY=keep-me\nTHEMI_VERSION=1.2.0\n")
    assert "THEMI_IMAGE=ghcr.io/madicen/themi" in env and "THEMI_VERSION=latest" not in env


def test_funnel_gives_the_website_its_address(host: Host) -> None:
    done = host.run(THEMI_FUNNEL="yes", FAKE_CODE="ABCD-EFGH")
    assert done.returncode == 0, done.stderr + done.stdout
    assert "sudo tailscale funnel --bg 8080" in host.calls()
    assert "THEMI_PUBLIC_URL=https://themi.tail1234.ts.net" in host.env_file()
    assert "Themi's website: https://themi.tail1234.ts.net" in done.stdout


def test_it_says_what_to_do_when_the_image_cant_be_pulled(host: Host) -> None:
    done = host.run(FAKE_PULL="1")
    assert done.returncode == 1
    assert "docker login ghcr.io" in done.stdout
    assert "docker compose up -d" not in host.calls()


def test_it_installs_only_on_linux(host: Host) -> None:
    done = host.run(FAKE_OS="Darwin")
    assert done.returncode == 1 and "Themi installs on Linux" in done.stderr
    assert host.calls() == []
