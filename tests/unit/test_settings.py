from pathlib import Path

import pytest

from themi.settings import Settings, SettingsError, read_dotenv
from themi.storage.secrets import generate_key

KEY = generate_key()


def test_minimal_settings_use_defaults() -> None:
    settings = Settings.from_mapping({"THEMI_SECRET_KEY": KEY})
    assert settings.db_path == Path("data/themi.db")
    assert settings.log_level == "INFO"
    assert settings.telegram_bot_token is None
    assert settings.secret_key.reveal() == KEY
    assert settings.cipher().decrypt(settings.cipher().encrypt("x")).reveal() == "x"


def test_missing_secret_key_explains_what_to_do() -> None:
    with pytest.raises(SettingsError, match=r"THEMI_SECRET_KEY.*themi keygen"):
        Settings.from_mapping({})


def test_malformed_secret_key_is_rejected() -> None:
    with pytest.raises(SettingsError, match="not a valid key"):
        Settings.from_mapping({"THEMI_SECRET_KEY": "short"})


def test_secret_key_from_file(tmp_path: Path) -> None:
    key_file = tmp_path / "themi.key"
    key_file.write_text(KEY + "\n")
    settings = Settings.from_mapping({"THEMI_SECRET_KEY_FILE": str(key_file)})
    assert settings.secret_key.reveal() == KEY


def test_unreadable_key_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="can't be read"):
        Settings.from_mapping({"THEMI_SECRET_KEY_FILE": str(tmp_path / "missing.key")})


def test_several_problems_are_reported_together() -> None:
    with pytest.raises(SettingsError) as info:
        Settings.from_mapping({"THEMI_LOG_LEVEL": "loud"})
    assert "THEMI_SECRET_KEY" in str(info.value) and "THEMI_LOG_LEVEL" in str(info.value)


def test_tokens_are_wrapped_and_masked() -> None:
    settings = Settings.from_mapping(
        {"THEMI_SECRET_KEY": KEY, "TELEGRAM_BOT_TOKEN": "123456:ABCDEF", "THEMI_LOG_LEVEL": "debug"}
    )
    assert settings.telegram_bot_token is not None
    assert settings.telegram_bot_token.reveal() == "123456:ABCDEF"
    assert "ABCDEF" not in repr(settings)
    assert KEY not in repr(settings)
    assert settings.log_level == "DEBUG"


def test_environment_wins_over_dotenv(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"THEMI_SECRET_KEY={KEY}\nTHEMI_DB_PATH=from-dotenv.db\n")
    settings = Settings.load(env={"THEMI_DB_PATH": "from-env.db"}, dotenv=dotenv)
    assert settings.db_path == Path("from-env.db")
    assert settings.secret_key.reveal() == KEY


def test_public_url_trailing_slash_is_trimmed() -> None:
    settings = Settings.from_mapping(
        {"THEMI_SECRET_KEY": KEY, "THEMI_PUBLIC_URL": "https://themi.example.ts.net/"}
    )
    assert settings.public_url == "https://themi.example.ts.net"


def test_read_dotenv_handles_comments_quotes_and_export(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("# comment\n\nA=1\nexport B='two words'\nC=\"3\"\nnot a pair\nD = spaced \n")
    assert read_dotenv(dotenv) == {"A": "1", "B": "two words", "C": "3", "D": "spaced"}
    assert read_dotenv(tmp_path / "absent.env") == {}
