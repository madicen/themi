"""SP7a: claiming a new Themi with its one-time code."""

from __future__ import annotations

import stat
from datetime import timedelta
from pathlib import Path

import pytest

from tests.fixtures.db import migrated_file
from themi import clock
from themi.accounts import AccountStore, Role
from themi.accounts.claim import CODE_FILE, Claim, ClaimError
from themi.storage.secrets import Cipher, generate_key


@pytest.fixture
def claim(tmp_path: Path) -> Claim:
    return Claim(AccountStore(migrated_file(tmp_path / "themi.db"), Cipher(generate_key())))


def test_a_code_is_made_and_written_for_its_owner_only(claim: Claim, tmp_path: Path) -> None:
    assert claim.needed()
    code = claim.make(tmp_path)
    assert len(code) == 9 and code[4] == "-"
    path = tmp_path / CODE_FILE
    assert path.read_text().strip() == code
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = claim.make(tmp_path)  # a new start, a new code; the old one stops working
    with pytest.raises(ClaimError, match="isn't the code"):
        claim.check(code if code != again else "WRONG-CODE")


def test_the_code_makes_the_household_and_its_first_admin(claim: Claim, tmp_path: Path) -> None:
    code = claim.make(tmp_path)
    typed = code.lower().replace("-", " ")  # read off a log, typed loosely
    admin = claim.claim(typed, "The Smiths", "America/Chicago", "Sam", tmp_path, "work")
    assert admin.role == Role.ADMIN and admin.name == "Sam"
    family = claim.store.get_family()
    assert family is not None and family.name == "The Smiths"
    assert family.timezone == "America/Chicago" and family.template == "work"
    assert not (tmp_path / CODE_FILE).exists()
    assert not claim.needed() and claim.claimant() == admin.id
    with pytest.raises(ClaimError, match="claimed already"):
        claim.claim(code, "Others", "UTC", "Eve", tmp_path)


def test_a_wrong_answer_changes_nothing(claim: Claim, tmp_path: Path) -> None:
    code = claim.make(tmp_path)
    with pytest.raises(ClaimError, match="timezone"):
        claim.claim(code, "The Smiths", "Mars/Olympus", "Sam", tmp_path)
    with pytest.raises(ClaimError, match="name"):
        claim.claim(code, "", "UTC", "Sam", tmp_path)
    assert claim.needed()


def test_wrong_codes_lock_it_for_a_while(claim: Claim, tmp_path: Path) -> None:
    clock.freeze(clock.now())
    try:
        code = claim.make(tmp_path)
        for _ in range(5):
            with pytest.raises(ClaimError, match="isn't the code"):
                claim.check("AAAA-AAAA")
        with pytest.raises(ClaimError, match="Too many wrong codes"):
            claim.check(code)  # even the right one, for now
        clock.advance(timedelta(minutes=11))
        claim.check(code)
    finally:
        clock.unfreeze()


def test_the_key_saved_is_noted(claim: Claim, tmp_path: Path) -> None:
    claim.claim(claim.make(tmp_path), "The Smiths", "UTC", "Sam", tmp_path)
    assert not claim.key_saved()
    claim.note_key_saved()
    assert claim.key_saved()
