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

from themi.updates import FINISHED_STATES, _moment, _version

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
        for name in ("update.sh", "control.sh"):
            (self.dir / name).write_text((REPO / "deploy" / name).read_text())
            (self.dir / name).chmod(0o755)
        self.control = self.dir / "control"
        self.control.mkdir()
        self.github = root / "github"
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
        return self.run("update.sh", *args, settings=settings, **fake)

    def run(
        self, script: str, *args: str, settings: dict[str, str] | None = None, **fake: str
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
        env["GITHUB_API"] = self.github.as_uri()  # D3b: no network
        return subprocess.run(
            [str(self.dir / script), *args], env=env, capture_output=True, text=True
        )

    # ----- D3b: the runner for the website's Update and Restart -----------------------------

    def release(self, tag: str) -> None:
        """GitHub's stand-in: `tag` is the latest release of ghcr.io/x/themi's repo."""
        latest = self.github / "repos" / "x" / "themi" / "releases" / "latest"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(json.dumps({"tag_name": tag, "name": "ignored"}))

    def ask(self, request: object) -> None:
        (self.control / "request.json").write_text(
            request if isinstance(request, str) else json.dumps(request)
        )

    def result(self) -> dict:
        return json.loads((self.control / "result.json").read_text())

    def runner(self) -> dict:
        return json.loads((self.control / "runner.json").read_text())

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


# ----- D3b: control.sh, the runner for the website's buttons --------------------------------


def test_an_update_goes_to_the_newest_release(server: Server) -> None:
    server.release("v1.1.0")
    server.ask({"id": 7, "action": "update", "version": "newest", "asked_by": "Erin"})
    done = server.run("control.sh", migrates="1.1.0")
    assert done.returncode == 0, done.stderr
    assert server.version() == "1.1.0" and "migrated_1_1_0" in server.tables()
    result = server.result()
    assert {k: result[k] for k in ("id", "state", "from", "to")} == {
        "id": 7,
        "state": "done",
        "from": "1.0.0",
        "to": "1.1.0",
    }
    assert "now on 1.1.0 (was 1.0.0)" in result["detail"] and result["finished_at"]
    assert server.runner()["newest"] == "1.1.0"
    assert not (server.control / "request.json").exists()
    assert sorted(p.name for p in server.control.iterdir()) == ["result.json", "runner.json"]
    # What themi.updates reads (D3a): the same shapes, so the two sides agree.
    assert result["state"] in FINISHED_STATES and _version(result["to"]) == "1.1.0"
    assert _moment(result["finished_at"]) and _moment(server.runner()["checked_at"])


def test_a_restart_pulls_the_running_version_again(server: Server) -> None:
    server.release("v1.1.0")
    server.ask({"id": 8, "action": "restart", "version": "current"})
    done = server.run("control.sh")
    assert done.returncode == 0, done.stderr
    assert server.version() == "1.0.0"
    assert (server.result()["state"], server.result()["to"]) == ("done", "1.0.0")
    assert "compose pull themi" in server.calls() and "compose up -d themi" in server.calls()


def test_already_on_the_newest_restarts_nothing(server: Server) -> None:
    server.release("v1.0.0")
    server.ask({"id": 9, "action": "update", "version": "newest"})
    assert server.run("control.sh").returncode == 0
    assert server.result()["state"] == "done" and server.result()["to"] == "1.0.0"
    assert not server.log.exists()  # docker never ran


@pytest.mark.parametrize(
    "request_text",
    [
        json.dumps({"id": 1, "action": "update", "version": "1.1.0; rm -rf /"}),
        json.dumps({"id": 1, "action": "shell", "version": "newest"}),
        json.dumps({"id": 1, "action": "restart", "version": "newest"}),
        json.dumps({"id": "1", "action": "update", "version": "newest"}),
        "not json",
    ],
)
def test_a_request_it_does_not_know_is_refused(server: Server, request_text: str) -> None:
    server.release("v1.1.0")
    server.ask(request_text)
    done = server.run("control.sh")
    assert done.returncode == 1 and "refused" in done.stderr
    assert server.result()["state"] == "refused"
    assert server.version() == "1.0.0" and not server.log.exists()


def test_a_failed_update_is_reported_as_failed(server: Server) -> None:
    server.release("v1.1.0")
    server.ask({"id": 3, "action": "update", "version": "newest"})
    done = server.run("control.sh", unhealthy="1.1.0")
    assert done.returncode == 1
    result = server.result()
    assert (result["state"], result["from"], result["to"]) == ("failed", "1.0.0", "1.1.0")
    assert "back on 1.0.0" in result["detail"]
    assert server.version() == "1.0.0"


def test_no_release_found_is_reported_as_failed(server: Server) -> None:
    server.ask({"id": 4, "action": "update", "version": "newest"})  # GitHub has nothing
    assert server.run("control.sh").returncode == 1
    assert (server.result()["state"], server.result()["to"]) == ("failed", None)
    assert not server.log.exists()


def test_a_request_runs_once(server: Server) -> None:
    server.release("v1.1.0")
    server.ask({"id": 5, "action": "update", "version": "newest"})
    assert server.run("control.sh").returncode == 0
    pulls = server.calls().count("compose pull themi")
    assert server.run("control.sh").returncode == 0  # nothing waiting: only a check
    assert server.calls().count("compose pull themi") == pulls
    assert server.result()["id"] == 5


def test_the_daily_check_only_notes_the_newest_release(server: Server) -> None:
    server.release("v1.2.0")
    assert server.run("control.sh", "--check").returncode == 0
    runner = server.runner()
    assert runner["newest"] == "1.2.0" and runner["installed_at"] and runner["checked_at"]
    installed = runner["installed_at"]
    with (server.dir / ".env").open("a") as env:
        env.write("THEMI_GITHUB_TOKEN=github_pat_secret\n")  # a private repository
    server.release("1.3.0")
    server.run("control.sh", "--check")
    assert server.runner() == {**server.runner(), "newest": "1.3.0", "installed_at": installed}
    assert not server.log.exists()


def test_the_repo_comes_from_the_image_or_its_own_setting(server: Server) -> None:
    (server.dir / ".env").write_text(
        "THEMI_IMAGE=ghcr.io/x/themi\nTHEMI_VERSION=1.0.0\nTHEMI_REPO=someone/else\n"
    )
    server.release("v1.2.0")  # x/themi's, which THEMI_REPO overrides
    server.run("control.sh", "--check")
    assert server.runner()["newest"] is None


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


def _next_version(repo: Path, bump: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REPO / "tools" / "next_version.sh"), bump], cwd=repo, capture_output=True, text=True
    )


@pytest.fixture
def tagged(tmp_path: Path) -> Path:
    """A repository with release tags out of order, and tags that aren't releases."""
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(tmp_path)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "first"], check=True)
    for tag in ["v0.2.0", "v0.10.1", "v0.9.0", "v1.0.0-rc1", "nightly"]:
        subprocess.run([*git, "tag", tag], check=True)
    return tmp_path


@pytest.mark.parametrize(
    ("bump", "expected"), [("patch", "0.10.2"), ("minor", "0.11.0"), ("major", "1.0.0")]
)
def test_the_next_version_counts_up_from_the_latest_release(
    tagged: Path, bump: str, expected: str
) -> None:
    done = _next_version(tagged, bump)
    assert done.stdout.strip() == expected, done.stderr


def test_the_first_release_counts_up_from_nothing(tagged: Path) -> None:
    subprocess.run(
        ["git", "-C", str(tagged), "tag", "-d", "v0.2.0", "v0.10.1", "v0.9.0"],
        check=True,
        capture_output=True,
    )
    assert _next_version(tagged, "minor").stdout.strip() == "0.1.0"


def test_the_next_version_wants_a_kind_of_bump(tagged: Path) -> None:
    done = _next_version(tagged, "huge")
    assert done.returncode == 2 and "usage" in done.stderr
