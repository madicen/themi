import pickle

import pytest

from themi.storage import open_database
from themi.storage.secrets import (
    Cipher,
    DecryptionError,
    Secret,
    SecretKeyError,
    SecretStore,
    generate_key,
)


def test_secret_never_prints_its_value() -> None:
    secret = Secret("hunter2")
    assert "hunter2" not in str(secret)
    assert "hunter2" not in repr(secret)
    assert "hunter2" not in f"{secret} {secret!r} {[secret]}"
    assert secret.reveal() == "hunter2"


def test_secret_comparison_hashing_and_pickling() -> None:
    assert Secret("a") == Secret("a")
    assert Secret("a") != Secret("b")
    assert not Secret("") and Secret("x")
    with pytest.raises(TypeError):
        hash(Secret("a"))
    with pytest.raises(TypeError):
        pickle.dumps(Secret("a"))
    with pytest.raises(TypeError):
        Secret(123)  # type: ignore[arg-type]


def test_encrypt_round_trip() -> None:
    cipher = Cipher(generate_key())
    token = cipher.encrypt("refresh-token-value")
    assert b"refresh-token-value" not in token
    assert cipher.decrypt(token).reveal() == "refresh-token-value"
    assert cipher.decrypt(cipher.encrypt(Secret("wrapped"))).reveal() == "wrapped"


def test_wrong_key_fails_loudly() -> None:
    token = Cipher(generate_key()).encrypt("value")
    with pytest.raises(DecryptionError, match="wrong THEMI_SECRET_KEY"):
        Cipher(generate_key()).decrypt(token)


@pytest.mark.parametrize("bad", ["", "not-a-key", "x" * 44])
def test_malformed_key_is_rejected(bad: str) -> None:
    with pytest.raises(SecretKeyError, match="themi keygen"):
        Cipher(bad)


def test_secret_store_crud() -> None:
    store = SecretStore(open_database(":memory:"), Cipher(generate_key()))
    assert store.get("ourgroceries_password") is None
    store.put("ourgroceries_password", "pa55")
    store.put("tuya_client_secret", Secret("tuya"))
    assert store.get("ourgroceries_password") == Secret("pa55")
    store.put("ourgroceries_password", "changed")
    assert store.get("ourgroceries_password") == Secret("changed")
    assert store.names() == ["ourgroceries_password", "tuya_client_secret"]
    store.delete("tuya_client_secret")
    assert store.names() == ["ourgroceries_password"]
