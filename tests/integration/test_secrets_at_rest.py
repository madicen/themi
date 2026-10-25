"""Secrets written through the store never appear in the database files on disk."""

from pathlib import Path

from themi.storage import open_database
from themi.storage.secrets import Cipher, SecretStore, generate_key

PLAINTEXT = "1//0g-very-distinctive-refresh-token-value-for-scanning"


def db_file_bytes(db_path: Path) -> bytes:
    data = b""
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{db_path}{suffix}")
        if candidate.exists():
            data += candidate.read_bytes()
    return data


def test_encrypted_secret_is_absent_from_raw_db_files(tmp_path: Path) -> None:
    db_path = tmp_path / "themi.db"
    key = generate_key()

    db = open_database(db_path)
    SecretStore(db, Cipher(key)).put("gmail_refresh_token", PLAINTEXT)
    raw_while_open = db_file_bytes(db_path)
    db.close()
    raw_after_close = db_file_bytes(db_path)

    for raw in (raw_while_open, raw_after_close):
        assert raw, "database files should exist"
        assert PLAINTEXT.encode() not in raw

    reopened = open_database(db_path)
    secret = SecretStore(reopened, Cipher(key)).get("gmail_refresh_token")
    assert secret is not None and secret.reveal() == PLAINTEXT
