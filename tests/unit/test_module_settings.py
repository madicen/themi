"""CR5b: each connector module's settings, from today's variables and from themi.toml.

The four "off until both are set" tests moved here from test_settings.py with the core
`Settings` fields they checked; their variables, defaults and messages are unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest

from themi.core.connector_settings import SearchSettings
from themi.modules.settings import (
    ModuleSettings,
    SettingsProblem,
    env_field,
    plain_values,
    read_settings,
)
from themi.storage.secrets import Secret
from themi_cozyla.settings import CozylaSettings  # CR21c: the wall's own pack
from themi_google.google_settings import GoogleSettings
from themi_home.home_settings import (
    HomeConnectSettings,
    OurGroceriesSettings,
    ThinqSettings,
)


def read[S: ModuleSettings](model: type[S], section: dict[str, Any] | None = None, **env: str) -> S:
    return read_settings(model, env, section or {}, "the_module")


def test_google_is_off_until_both_keys_are_set() -> None:
    assert read(GoogleSettings).config() is None
    with pytest.raises(SettingsProblem, match="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET"):
        read(GoogleSettings, GOOGLE_CLIENT_ID="abc")


def test_google_settings_and_endpoint_overrides() -> None:
    google = read(
        GoogleSettings,
        GOOGLE_CLIENT_ID="abc.apps.googleusercontent.com",
        GOOGLE_CLIENT_SECRET="shh",
        GOOGLE_TOKEN_URL="http://127.0.0.1:8765/token",
    ).config()
    assert google is not None
    assert google.client_id == "abc.apps.googleusercontent.com"
    assert google.client_secret.reveal() == "shh" and "shh" not in repr(google)
    assert google.token_url == "http://127.0.0.1:8765/token"
    assert google.auth_url == "https://accounts.google.com/o/oauth2/v2/auth"  # default kept


def test_ourgroceries_is_off_until_both_login_parts_are_set() -> None:
    assert read(OurGroceriesSettings).config() is None
    with pytest.raises(SettingsProblem, match="OURGROCERIES_USERNAME and OURGROCERIES_PASSWORD"):
        read(OurGroceriesSettings, OURGROCERIES_USERNAME="us@x.example")
    config = read(
        OurGroceriesSettings, OURGROCERIES_USERNAME="us@x.example", OURGROCERIES_PASSWORD="pw"
    ).config()
    assert config is not None
    assert (config.username, config.password.reveal(), config.list_name) == (
        "us@x.example",
        "pw",
        "Groceries",
    )
    assert "pw" not in repr(config)


def test_home_connect_is_off_until_both_keys_are_set() -> None:
    assert read(HomeConnectSettings).config() is None
    with pytest.raises(
        SettingsProblem, match="HOME_CONNECT_CLIENT_ID and HOME_CONNECT_CLIENT_SECRET"
    ):
        read(HomeConnectSettings, HOME_CONNECT_CLIENT_ID="abc")
    with pytest.raises(SettingsProblem, match="HOME_CONNECT_URL must be an https"):
        read(HomeConnectSettings, HOME_CONNECT_URL="http://x.example")
    config = read(
        HomeConnectSettings,
        HOME_CONNECT_CLIENT_ID="abc",
        HOME_CONNECT_CLIENT_SECRET="shh",
        HOME_CONNECT_URL="https://simulator.home-connect.com/",
    ).config()
    assert config is not None
    assert (config.client_id, config.client_secret.reveal(), config.base_url) == (
        "abc",
        "shh",
        "https://simulator.home-connect.com",
    )
    assert "shh" not in repr(config)


def test_cozyla_is_off_until_both_login_parts_are_set() -> None:
    assert read(CozylaSettings).config() is None
    with pytest.raises(SettingsProblem, match="COZYLA_EMAIL and COZYLA_PASSWORD"):
        read(CozylaSettings, COZYLA_PASSWORD="pw")
    config = read(CozylaSettings, COZYLA_EMAIL="us@x.example", COZYLA_PASSWORD="pw").config()
    assert config is not None
    assert (config.email, config.password.reveal(), config.todo_list, config.device_sn) == (
        "us@x.example",
        "pw",
        "",  # no list: the check works, nothing syncs
        "themi",
    )
    assert "pw" not in repr(config)
    listed = read(
        CozylaSettings,
        COZYLA_EMAIL="us@x.example",
        COZYLA_PASSWORD="pw",
        COZYLA_TODO_LIST=" Family ",
        COZYLA_DEVICE_SN="themi-home",
        COZYLA_CHORES="yes",
    ).config()
    assert listed is not None and (listed.todo_list, listed.device_sn) == ("Family", "themi-home")
    assert listed.chores


def test_thinq_url_must_be_https() -> None:
    with pytest.raises(SettingsProblem, match="THINQ_URL must be an https"):
        read(ThinqSettings, THINQ_URL="http://lg.example")
    assert read(ThinqSettings, THINQ_URL="https://lg.example/").config().base_url == (
        "https://lg.example"
    )


# ----- themi.toml sections -------------------------------------------------------------


def test_a_plain_setting_can_come_from_themi_toml_and_the_environment_wins() -> None:
    assert read(SearchSettings, {"backend": "firecrawl"}).backend == "firecrawl"
    assert read(
        SearchSettings, {"backend": "firecrawl"}, THEMI_SEARCH_BACKEND="tavily"
    ).backend == ("tavily")


def test_a_secret_is_never_read_from_themi_toml() -> None:
    with pytest.raises(SettingsProblem, match="tavily_api_key, a secret: set TAVILY_API_KEY"):
        read(SearchSettings, {"tavily_api_key": "in-the-file"})
    found = read(SearchSettings, TAVILY_API_KEY="from-env").tavily_api_key
    assert found == Secret("from-env")


def test_a_setting_a_module_does_not_have_is_named() -> None:
    with pytest.raises(SettingsProblem, match=r"\[module.the_module\] has colour"):
        read(SearchSettings, {"colour": "blue"})


def test_plain_values_leave_secrets_out() -> None:
    values = plain_values(read(GoogleSettings, GOOGLE_CLIENT_ID="id", GOOGLE_CLIENT_SECRET="s"))
    assert values["client_id"] == "id" and "client_secret" not in values


def test_a_bool_from_the_environment() -> None:
    class Flag(ModuleSettings):
        on: bool = env_field("FLAG", False)

    assert read(Flag, FLAG="1").on and read(Flag, FLAG="Yes").on and not read(Flag, FLAG="no").on
