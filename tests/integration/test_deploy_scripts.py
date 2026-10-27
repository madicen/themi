"""docs/RASPBERRY_PI.md, Part 1: `deploy/update.sh` against a stand-in `docker` (no Docker,
no network). The stand-in runs the script's own Python on a folder playing the data volume,
so copies and restores are real SQLite files; a version listed as unhealthy fails its health
check, and one listed as migrating changes the database when it starts, as a migration
would."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

FAKE_DOCKER = r"""#!PYTHON
import json, os, sqlite3, subprocess, sys
args = sys.argv[1:]
data = os.environ["FAKE_DATA"]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
env_version = ""
for line in open(".env"):
    if line.startswith("THEMI_VERSION="):
        env_version = line.strip().split("=", 1)[1]
version = os.environ.get("THEMI_VERSION") or env_version
if args[:2] == ["compose", "pull"]:
    sys.exit(1 if version in os.environ.get("FAKE_PULL_FAIL", "").split(",") else 0)
if args[:2] == ["compose", "up"]:
    with open(os.environ["FAKE_STATE"], "w") as state:
        state.write(env_version)
    if env_version in os.environ.get("FAKE_MIGRATES", "").split(","):
        db = sqlite3.connect(os.path.join(data, "themi.db"))
        db.execute(f"CREATE TABLE IF NOT EXISTS migrated_{env_version.replace('.', '_')} (x)")
        db.commit()
    sys.exit(0)
if args[:2] == ["compose", "ps"]:
    print("container-1")
    sys.exit(0)
if args[0] == "inspect":
    running = open(os.environ["FAKE_STATE"]).read()
    print("unhealthy" if running in os.environ.get("FAKE_UNHEALTHY", "").split(",") else "healthy")
    sys.exit(0)
if args[:2] == ["compose", "run"]:
    code = args[args.index("-c") + 1].replace("/data/", data + "/")
    sys.exit(subprocess.run([sys.executable, "-c", code, *args[args.index("-c") + 2:]]).returncode)
sys.exit(0)  # stop, exec ... backup: recorded only
"""


class Server:
    def __init__(self, root: Path) -> None:
        self.dir = root / "themi"
        self.data = root / "data"
        self.bin = root / "bin"
        for path in (self.dir, self.data, self.bin):
            path.mkdir()
        for name in ("update.sh",):
            (self.dir / name).write_text((REPO / "deploy" / name).read_text())
        (self.dir / "update.sh").chmod(0o755)
        (self.dir / "compose.yml").write_text((REPO / "deploy" / "compose.yml").read_text())
        (self.dir / ".env").write_text("THEMI_IMAGE=ghcr.io/x/themi\nTHEMI_VERSION=1.0.0\n")
        docker = self.bin / "docker"
        docker.write_text(FAKE_DOCKER.replace("PYTHON", sys.executable, 1))
        docker.chmod(0o755)
        self.log = root / "docker.log"
        self.state = root / "running"
        self.state.write_text("1.0.0")
        db = sqlite3.connect(self.data / "themi.db")
        db.execute("CREATE TABLE tasks (title)")
        db.execute("INSERT INTO tasks VALUES ('Clean the bird cage')")
        db.commit()
        db.close()

    def update(
        self, *args: str, settings: dict[str, str] | None = None, **fake: str
    ) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            **(settings or {}),
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DATA": str(self.data),
            "FAKE_LOG": str(self.log),
            "FAKE_STATE": str(self.state),
            **{f"FAKE_{k.upper()}": v for k, v in fake.items()},
        }
        env.pop("THEMI_VERSION", None)
        return subprocess.run(
            [str(self.dir / "update.sh"), *args], env=env, capture_output=True, text=True
        )

    def version(self) -> str:
        line = next(
            x
            for x in (self.dir / ".env").read_text().splitlines()
            if x.startswith("THEMI_VERSION=")
        )
        return line.split("=", 1)[1]

    def tables(self, name: str = "themi.db") -> set[str]:
        db = sqlite3.connect(self.data / name)
        found = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        db.close()
        return found

    def calls(self) -> list[str]:
        return [" ".join(json.loads(line)) for line in self.log.read_text().splitlines()]


@pytest.fixture
def server(tmp_path: Path) -> Server:
    return Server(tmp_path)


def test_an_upgrade_copies_first_and_switches_the_version(server: Server) -> None:
    done = server.update("1.1.0", migrates="1.1.0")
    assert done.returncode == 0, done.stderr
    assert "now on 1.1.0 (was 1.0.0)" in done.stdout
    assert server.version() == "1.1.0"
    assert "migrated_1_1_0" in server.tables()
    assert server.tables("themi.db.before-1.1.0") == {"tasks"}  # the copy, from before
    calls = server.calls()
    assert calls.index("compose pull themi") < calls.index("compose up -d themi")  # pulled first


def test_an_unhealthy_version_goes_back_with_the_database_from_before(server: Server) -> None:
    done = server.update("1.1.0", migrates="1.1.0", unhealthy="1.1.0")
    assert done.returncode == 1
    assert "back on 1.0.0 with the database from before" in done.stderr
    assert server.version() == "1.0.0"
    assert server.tables() == {"tasks"}  # the migration undone
    assert "migrated_1_1_0" in server.tables("themi.db.failed-1.1.0")  # kept, to look at


def test_a_failed_pull_changes_nothing(server: Server) -> None:
    done = server.update("1.1.0", pull_fail="1.1.0")
    assert done.returncode == 1 and "nothing changed" in done.stderr
    assert server.version() == "1.0.0"
    assert not (server.data / "themi.db.before-1.1.0").exists()
    assert "compose up -d themi" not in server.calls()


def test_going_back_by_hand(server: Server) -> None:
    assert server.update("1.1.0", migrates="1.1.0").returncode == 0
    done = server.update("1.0.0", "--restore")
    assert done.returncode == 0, done.stderr
    assert server.version() == "1.0.0"
    assert server.tables() == {"tasks"}


def test_only_the_last_few_copies_are_kept(server: Server) -> None:
    for version in ("1.1.0", "1.2.0", "1.3.0", "1.4.0"):
        done = server.update(version, settings={"KEEP_COPIES": "2"})
        assert done.returncode == 0, done.stderr
    copies = sorted(p.name for p in server.data.glob("themi.db.before-*"))
    assert copies == ["themi.db.before-1.3.0", "themi.db.before-1.4.0"]


def test_a_backup_to_storage_only_when_it_is_set_up(server: Server) -> None:
    server.update("1.1.0")
    assert "compose exec -T themi themi backup" not in server.calls()
    (server.dir / ".env").write_text(
        (server.dir / ".env").read_text() + "THEMI_BACKUP_BUCKET=themi-backups\n"
    )
    server.update("1.2.0")
    assert "compose exec -T themi themi backup" in server.calls()


def test_nonsense_is_refused(server: Server) -> None:
    done = server.update("../../etc")
    assert done.returncode == 1 and "not a version" in done.stderr
    usage = subprocess.run(
        [str(REPO / "tools" / "release.sh"), "1.4"], capture_output=True, text=True
    )
    assert usage.returncode == 2 and "usage: tools/release.sh 1.4.0" in usage.stderr


def test_a_released_image_says_its_version() -> None:
    """The release workflow builds with THEMI_BUILD_VERSION from the tag."""
    env = {**os.environ, "THEMI_BUILD_VERSION": "1.4.0"}
    out = subprocess.run(
        [sys.executable, "-c", "from themi.cli import main; main(['--version'])"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip() == "themi 1.4.0", out.stderr
