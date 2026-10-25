"""Backups end to end: a real SQLite database, encrypted, to a fake S3 over HTTP, and back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.s3_api import FakeS3
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.backup import BackupConfig, BackupError, Backups, S3Error
from themi.backup.job import BackupJob
from themi.backup.s3 import S3Client
from themi.backup.snapshots import Snapshot, to_prune
from themi.cli import main
from themi.storage import open_database
from themi.storage.secrets import Cipher, DecryptionError, Secret, generate_key

NOW = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)


@pytest.fixture
def backups(family: SeededFamily, fake_s3: FakeS3, frozen_clock: datetime) -> Backups:
    return Backups(BackupConfig(fake_s3.config()), family.store.cipher)


def seed_secrets(family: SeededFamily) -> None:
    family.store.add_linked_account(
        family.erin, family.erin.id, "gmail", "erin@gmail.com", Secret("1//refresh-token-xyz")
    )


# ----- the round trip ----------------------------------------------------------------


async def test_backup_and_restore_round_trip(
    family: SeededFamily, backups: Backups, tmp_path: Path
) -> None:
    seed_secrets(family)
    snapshot = await backups.create(family.db)
    assert snapshot.key.startswith("themi/themi-") and snapshot.key.endswith(".sqlite.gz.enc")
    assert [s.key for s in await backups.snapshots()] == [snapshot.key]

    target = tmp_path / "restored" / "themi.db"
    dry = await backups.restore("latest", target, dry_run=True)
    assert dry.integrity == "ok" and dry.counts["members"] == 2
    assert not target.exists()  # a dry run changes nothing

    report = await backups.restore(snapshot.key.split("/")[-1], target, dry_run=False)
    assert report.restored_to == target and report.previous_moved_to is None
    restored = open_database(target)
    names = {r["name"] for r in restored.query("SELECT name FROM members")}
    assert names == {"Erin", "Husband"}
    # Secrets come back still encrypted, and the same key opens them.
    from themi.accounts import AccountStore

    store = AccountStore(restored, family.store.cipher)
    (account,) = store.linked_accounts(family.erin.id)
    assert store.refresh_token(account.id).reveal() == "1//refresh-token-xyz"


async def test_restoring_over_a_database_keeps_the_old_one(
    family: SeededFamily, backups: Backups, tmp_path: Path
) -> None:
    await backups.create(family.db)
    target = tmp_path / "themi.db"
    target.write_bytes(b"the old database")
    Path(f"{target}-wal").write_bytes(b"old journal")
    report = await backups.restore("latest", target, dry_run=False)
    assert report.previous_moved_to is not None
    assert report.previous_moved_to.read_bytes() == b"the old database"
    assert not Path(f"{target}-wal").exists()  # the old journal can't replay onto it
    assert open_database(target).scalar("SELECT COUNT(*) FROM members") == 2


async def test_the_snapshot_has_no_plaintext(
    family: SeededFamily, backups: Backups, fake_s3: FakeS3
) -> None:
    seed_secrets(family)
    family.store.update_family(family.erin, staples=("olive oil", "cardamom pods"))
    snapshot = await backups.create(family.db)
    stored = fake_s3.objects[snapshot.key]
    for needle in (b"SQLite format 3", b"Erin", b"Husband", b"cardamom", b"erin@gmail.com"):
        assert needle not in stored
    assert b"refresh-token-xyz" not in stored
    assert stored.startswith(b"gAAAAA")  # a Fernet token


async def test_a_snapshot_needs_the_same_key(
    family: SeededFamily, backups: Backups, fake_s3: FakeS3, tmp_path: Path
) -> None:
    await backups.create(family.db)
    stranger = Backups(BackupConfig(fake_s3.config()), Cipher(generate_key()))
    with pytest.raises(DecryptionError, match="wrong THEMI_SECRET_KEY"):
        await stranger.restore("latest", tmp_path / "x.db", dry_run=True)
    fake_s3.objects[next(iter(fake_s3.objects))] = b"gAAAAAtampered"
    with pytest.raises(DecryptionError):
        await backups.restore("latest", tmp_path / "x.db", dry_run=True)


async def test_a_snapshot_from_a_newer_themi_is_refused(
    family: SeededFamily, backups: Backups, tmp_path: Path
) -> None:
    family.db.execute(
        "INSERT INTO schema_version (version, name, applied_at) VALUES (9999, 'future', 'x')"
    )
    await backups.create(family.db)
    with pytest.raises(BackupError, match="newer Themi"):
        await backups.restore("latest", tmp_path / "x.db", dry_run=False)
    assert not (tmp_path / "x.db").exists()


async def test_unknown_snapshot_names_and_empty_storage(backups: Backups, tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="no snapshots"):
        await backups.find("latest")


# ----- retention ---------------------------------------------------------------------


def snapshot_at(days_ago: float) -> Snapshot:
    taken = NOW - timedelta(days=days_ago)
    return Snapshot(f"themi/themi-{taken.strftime('%Y%m%dT%H%M%SZ')}.sqlite.gz.enc", taken, 1)


def test_retention_keeps_thirty_days_and_always_the_newest() -> None:
    snaps = [snapshot_at(d) for d in (0.5, 10, 29.9, 30.1, 45, 90)]
    assert [round((NOW - s.taken_at).days) for s in to_prune(snaps, NOW, 30)] == [30, 45, 90]
    only_old = [snapshot_at(d) for d in (40, 50)]
    assert to_prune(only_old, NOW, 30) == [only_old[1]]  # the newest stays, however old
    assert to_prune([], NOW, 30) == []


async def test_pruning_deletes_old_snapshots_and_leaves_other_files(
    backups: Backups, fake_s3: FakeS3, frozen_clock: datetime
) -> None:
    def name(days: int) -> str:
        taken = frozen_clock - timedelta(days=days)
        return f"themi/themi-{taken.strftime('%Y%m%dT%H%M%SZ')}.sqlite.gz.enc"

    for days in (1, 31, 60):
        fake_s3.put_object(name(days), b"x")
    fake_s3.put_object("themi/notes.txt", b"not a snapshot")
    fake_s3.page_size = 2  # listing pages through
    pruned = await backups.prune()
    assert len(pruned) == 2
    assert sorted(fake_s3.objects) == ["themi/notes.txt", name(1)]


async def test_storage_errors_are_reported_plainly(backups: Backups, fake_s3: FakeS3) -> None:
    fake_s3.fail("list", 503)
    with pytest.raises(S3Error, match="HTTP 503: SlowDown"):
        await backups.snapshots()
    bad = S3Client(fake_s3.config(secret="wrong"))
    with pytest.raises(S3Error, match="SignatureDoesNotMatch"):
        await bad.list("themi/")


# ----- the nightly job ---------------------------------------------------------------


async def test_the_nightly_job_backs_up_once_a_day(
    family: SeededFamily, backups: Backups, fake_s3: FakeS3, frozen_clock: datetime
) -> None:
    sent: list[str] = []

    class Outbox:
        async def send(self, member, text, **kwargs):  # type: ignore[no-untyped-def]
            sent.append(text)

    job = BackupJob(family.store, backups, Outbox())  # type: ignore[arg-type]
    assert (await job.run()).startswith("saved themi/")
    assert await job.run() == "not due"
    clock.advance(timedelta(hours=23, minutes=5))
    assert (await job.run()).startswith("saved")
    assert len(fake_s3.objects) == 2

    # Storage goes away: failures are recorded; after two days the admin hears, once a day.
    fake_s3.fail("put", 503, times=100)
    for _ in range(3 * 24):
        clock.advance(timedelta(hours=1))
        await job.run()
    runs = family.db.query("SELECT status, error FROM backup_runs ORDER BY id")
    assert runs[0]["status"] == runs[1]["status"] == "ok"
    assert {r["status"] for r in runs[2:]} == {"failed"}
    assert "S3Error" in runs[-1]["error"]
    assert sent and all(t.startswith("Themi's nightly backups haven't worked since") for t in sent)


# ----- the command line --------------------------------------------------------------


def test_the_cli_backs_up_lists_and_restores(
    fake_s3: FakeS3, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    db_path = tmp_path / "data" / "themi.db"
    env = {
        "THEMI_SECRET_KEY": generate_key(),
        "THEMI_DB_PATH": str(db_path),
        "THEMI_BACKUP_ENDPOINT": fake_s3.url,
        "THEMI_BACKUP_BUCKET": "themi-backups",
        "THEMI_BACKUP_ACCESS_KEY_ID": "TESTACCESSKEY",
        "THEMI_BACKUP_SECRET_ACCESS_KEY": "test/secret+key",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)  # no stray .env
    open_database(db_path).execute(
        "INSERT INTO family (id, name, timezone, created_at, updated_at) "
        "VALUES (1, 'Household', 'UTC', 'x', 'x')"
    )
    assert main(["backup"]) == 0
    assert "Backup saved themi/themi-" in capsys.readouterr().out
    assert main(["backup", "--list"]) == 0
    assert "1 snapshot(s); kept for 30 days." in capsys.readouterr().out

    with pytest.raises(SystemExit, match="Stop Themi"):
        main(["restore", "latest"])  # no --yes: refuses
    assert main(["restore", "latest", "--dry-run"]) == 0
    assert "Dry run: nothing was changed." in capsys.readouterr().out
    assert main(["restore", "latest", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Restored to" in out and "previous database is kept at" in out
