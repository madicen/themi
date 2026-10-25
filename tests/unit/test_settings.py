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


def test_google_is_off_until_both_keys_are_set() -> None:
    assert Settings.from_mapping({"THEMI_SECRET_KEY": KEY}).google() is None
    with pytest.raises(SettingsError, match="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET"):
        Settings.from_mapping({"THEMI_SECRET_KEY": KEY, "GOOGLE_CLIENT_ID": "abc"})


def test_google_settings_and_endpoint_overrides() -> None:
    settings = Settings.from_mapping(
        {
            "THEMI_SECRET_KEY": KEY,
            "GOOGLE_CLIENT_ID": "abc.apps.googleusercontent.com",
            "GOOGLE_CLIENT_SECRET": "shh",
            "GOOGLE_TOKEN_URL": "http://127.0.0.1:8765/token",
        }
    )
    google = settings.google()
    assert google is not None
    assert google.client_id == "abc.apps.googleusercontent.com"
    assert google.client_secret.reveal() == "shh" and "shh" not in repr(google)
    assert google.token_url == "http://127.0.0.1:8765/token"
    assert google.auth_url == "https://accounts.google.com/o/oauth2/v2/auth"  # default kept


def test_ourgroceries_is_off_until_both_login_parts_are_set() -> None:
    assert Settings.from_mapping({"THEMI_SECRET_KEY": KEY}).ourgroceries() is None
    with pytest.raises(SettingsError, match="OURGROCERIES_USERNAME and OURGROCERIES_PASSWORD"):
        Settings.from_mapping({"THEMI_SECRET_KEY": KEY, "OURGROCERIES_USERNAME": "us@x.example"})
    config = Settings.from_mapping(
        {
            "THEMI_SECRET_KEY": KEY,
            "OURGROCERIES_USERNAME": "us@x.example",
            "OURGROCERIES_PASSWORD": "pw",
        }
    ).ourgroceries()
    assert config is not None
    assert (config.username, config.password.reveal(), config.list_name) == (
        "us@x.example",
        "pw",
        "Groceries",
    )
    assert "pw" not in repr(config)


BACKUP = {
    "THEMI_BACKUP_ENDPOINT": "https://abc123.r2.cloudflarestorage.com/",
    "THEMI_BACKUP_BUCKET": "themi-backups",
    "THEMI_BACKUP_ACCESS_KEY_ID": "key-id",
    "THEMI_BACKUP_SECRET_ACCESS_KEY": "shh",
}


def test_backups_are_off_until_all_four_settings_are_there() -> None:
    assert Settings.from_mapping({"THEMI_SECRET_KEY": KEY}).backup is None
    partial = {"THEMI_SECRET_KEY": KEY, "THEMI_BACKUP_BUCKET": "b"}
    with pytest.raises(SettingsError, match="missing THEMI_BACKUP_ENDPOINT"):
        Settings.from_mapping(partial)
    backup = Settings.from_mapping({"THEMI_SECRET_KEY": KEY, **BACKUP}).backup
    assert backup is not None
    assert backup.s3.endpoint == "https://abc123.r2.cloudflarestorage.com"
    assert (backup.s3.region, backup.prefix, backup.keep_days) == ("auto", "themi/", 30)
    assert "shh" not in repr(backup)


def test_backup_settings_are_checked() -> None:
    plain = {**BACKUP, "THEMI_BACKUP_ENDPOINT": "http://storage.example"}
    with pytest.raises(SettingsError, match="must be an https:// address"):
        Settings.from_mapping({"THEMI_SECRET_KEY": KEY, **plain})
    with pytest.raises(SettingsError, match="1 to 365 days"):
        Settings.from_mapping({"THEMI_SECRET_KEY": KEY, **BACKUP, "THEMI_BACKUP_KEEP_DAYS": "0"})
    b2 = Settings.from_mapping(
        {
            "THEMI_SECRET_KEY": KEY,
            **BACKUP,
            "THEMI_BACKUP_REGION": "us-west-004",
            "THEMI_BACKUP_KEEP_DAYS": "14",
        }
    ).backup
    assert b2 is not None and (b2.s3.region, b2.keep_days) == ("us-west-004", 14)


def test_telegram_api_url_points_the_bot_at_another_server() -> None:
    assert Settings.from_mapping({"THEMI_SECRET_KEY": KEY}).telegram_api_url == ""
    settings = Settings.from_mapping(
        {"THEMI_SECRET_KEY": KEY, "TELEGRAM_API_URL": "http://127.0.0.1:8090/"}
    )
    assert settings.telegram_api_url == "http://127.0.0.1:8090"
    with pytest.raises(SettingsError, match="TELEGRAM_API_URL must be an http"):
        Settings.from_mapping({"THEMI_SECRET_KEY": KEY, "TELEGRAM_API_URL": "127.0.0.1:8090"})
