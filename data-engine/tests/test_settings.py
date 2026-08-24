"""Environment settings: fail closed, never guess."""

from pathlib import Path

import pytest

from egx_engine.settings import (
    DEFAULT_PROVIDER,
    PORTFOLIO_ID_ENV_VAR,
    Settings,
    SettingsError,
    load_settings,
)


def test_empty_environment_defaults_to_the_refusing_provider():
    settings = load_settings({})
    assert settings.provider_name == DEFAULT_PROVIDER
    assert settings.provider_data_dir is None
    assert settings.api_key is None
    assert settings.portfolio_id is None


def test_provider_name_is_normalised():
    assert load_settings({"MARKET_DATA_PROVIDER": "  Manual  "}).provider_name == "manual"


def test_whitespace_only_values_are_treated_as_absent():
    settings = load_settings(
        {"MARKET_DATA_PROVIDER": "   ", "MARKET_DATA_API_KEY": "  ", "MARKET_DATA_DIR": " "}
    )
    assert settings.provider_name == DEFAULT_PROVIDER
    assert settings.api_key is None
    assert settings.provider_data_dir is None


def test_data_dir_becomes_a_path():
    settings = load_settings({"MARKET_DATA_DIR": "/tmp/egx"})
    assert settings.provider_data_dir == Path("/tmp/egx")


def test_portfolio_id_is_parsed():
    assert load_settings({PORTFOLIO_ID_ENV_VAR: "7"}).portfolio_id == 7


@pytest.mark.parametrize("raw", ["abc", "1.5", "", " x "])
def test_unparseable_portfolio_id_is_refused(raw):
    if raw.strip() == "":
        # Blank is "absent", which is a different failure surfaced on use.
        assert load_settings({PORTFOLIO_ID_ENV_VAR: raw}).portfolio_id is None
        return
    with pytest.raises(SettingsError):
        load_settings({PORTFOLIO_ID_ENV_VAR: raw})


@pytest.mark.parametrize("raw", ["0", "-1"])
def test_non_positive_portfolio_id_is_refused(raw):
    with pytest.raises(SettingsError):
        load_settings({PORTFOLIO_ID_ENV_VAR: raw})


def test_missing_portfolio_id_fails_on_use_not_on_load():
    """Loading must not explode for commands that need no portfolio."""
    settings = load_settings({})
    with pytest.raises(SettingsError, match="refusing to guess"):
        settings.require_portfolio_id()


def test_missing_data_dir_fails_on_use():
    settings = Settings(provider_name="manual")
    with pytest.raises(SettingsError, match="MARKET_DATA_DIR"):
        settings.require_provider_data_dir()


def test_settings_are_frozen():
    settings = load_settings({})
    with pytest.raises(Exception):
        settings.provider_name = "manual"  # type: ignore[misc]
