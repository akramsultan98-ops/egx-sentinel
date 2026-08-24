"""Provider registry and the interim operator-supplied provider.

The manual provider gets no exemptions: what it returns still has to survive
validation like any vendor feed.
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from egx_engine.provider import MarketDataError, UnconfiguredProvider
from egx_engine.providers import (
    BAR_DIRECTORY,
    SNAPSHOT_FILE,
    ManualFileProvider,
    get_provider,
)
from egx_engine.settings import Settings, SettingsError
from egx_engine.validator import validate_snapshot

from conftest import NOW

SNAPSHOT = {
    "instrument_id": "TEST",
    "ticker": "TEST",
    "timestamp_utc": "2026-03-11T10:00:00+00:00",
    "session_date": "2026-03-11",
    "last_price": 10.1,
    "high": 10.5,
    "low": 9.5,
    "traded_value_egp": 5000000,
    "source": "manual",
    "source_timestamp": "2026-03-11T10:00:00+00:00",
    "freshness_seconds": 10,
}


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / SNAPSHOT_FILE).write_text(json.dumps([SNAPSHOT]), encoding="utf-8")
    bars = tmp_path / BAR_DIRECTORY
    bars.mkdir()
    (bars / "TEST.csv").write_text(
        "session_date,open,high,low,close,volume\n"
        "2026-03-09,10.0,10.2,9.8,10.0,1000\n"
        "2026-03-10,10.0,10.2,9.8,10.1,2000\n"
        "2026-03-11,10.1,10.3,9.9,10.2,3000\n",
        encoding="utf-8",
    )
    return tmp_path


# --- registry -------------------------------------------------------------


def test_default_settings_give_the_refusing_provider():
    provider = get_provider(Settings())
    assert isinstance(provider, UnconfiguredProvider)
    assert provider.health() is False
    with pytest.raises(MarketDataError):
        provider.snapshot(["TEST"])


def test_manual_provider_is_built_from_settings(data_dir):
    provider = get_provider(Settings(provider_name="manual", provider_data_dir=data_dir))
    assert isinstance(provider, ManualFileProvider)
    assert provider.name == "manual"


def test_manual_provider_without_a_directory_is_refused():
    with pytest.raises(SettingsError, match="MARKET_DATA_DIR"):
        get_provider(Settings(provider_name="manual"))


def test_an_unknown_provider_is_not_silently_downgraded():
    """A typo must be visible, not quietly reinterpreted as 'no data'."""
    with pytest.raises(SettingsError, match="unknown market-data provider"):
        get_provider(Settings(provider_name="bloomburg"))


# --- manual provider ------------------------------------------------------


def test_health_requires_a_snapshot_file(tmp_path, data_dir):
    assert ManualFileProvider(data_dir).health() is True
    assert ManualFileProvider(tmp_path / "nope").health() is False


def test_snapshot_prices_keep_full_decimal_precision(data_dir):
    """A float round-trip would turn 10.1 into 10.0999999999999996."""
    snapshot = ManualFileProvider(data_dir).snapshot(["TEST"])[0]
    assert snapshot.last_price == Decimal("10.1")
    assert str(snapshot.last_price) == "10.1"


def test_snapshot_is_stamped_unverified_until_validated(data_dir):
    snapshot = ManualFileProvider(data_dir).snapshot(["TEST"])[0]
    assert snapshot.validation_status == "UNVERIFIED"


def test_a_manual_snapshot_is_validated_like_any_other(data_dir):
    """No shortcut: the operator's own file still has to pass the validator."""
    provider = ManualFileProvider(data_dir)
    snapshot = provider.snapshot(["TEST"])[0]

    assert validate_snapshot(snapshot, now=NOW).valid is True

    stale = snapshot.model_copy(update={"freshness_seconds": 9999})
    result = validate_snapshot(stale, now=NOW)
    assert result.valid is False


def test_unrequested_tickers_are_not_returned(data_dir):
    assert ManualFileProvider(data_dir).snapshot(["OTHER"]) == []


def test_ticker_matching_ignores_case_and_padding(data_dir):
    assert len(ManualFileProvider(data_dir).snapshot([" test "])) == 1


def test_a_malformed_snapshot_is_refused(tmp_path):
    (tmp_path / SNAPSHOT_FILE).write_text(
        json.dumps([{**SNAPSHOT, "last_price": -1}]), encoding="utf-8"
    )
    with pytest.raises(MarketDataError, match="not a usable snapshot"):
        ManualFileProvider(tmp_path).snapshot(["TEST"])


def test_invalid_json_is_refused(tmp_path):
    (tmp_path / SNAPSHOT_FILE).write_text("{not json", encoding="utf-8")
    with pytest.raises(MarketDataError, match="not valid JSON"):
        ManualFileProvider(tmp_path).snapshot(["TEST"])


def test_a_missing_snapshot_file_is_refused(tmp_path):
    with pytest.raises(MarketDataError, match="could not read"):
        ManualFileProvider(tmp_path).snapshot(["TEST"])


def test_a_json_object_instead_of_an_array_is_refused(tmp_path):
    (tmp_path / SNAPSHOT_FILE).write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    with pytest.raises(MarketDataError, match="must contain a JSON array"):
        ManualFileProvider(tmp_path).snapshot(["TEST"])


# --- bars -----------------------------------------------------------------


def test_bars_are_read_in_range_and_ordered(data_dir):
    bars = ManualFileProvider(data_dir).daily_bars(
        "TEST", date(2026, 3, 9), date(2026, 3, 11)
    )
    assert [b.session_date.day for b in bars] == [9, 10, 11]
    assert bars[0].source == "manual"
    assert bars[2].close == Decimal("10.2")


def test_bars_outside_the_range_are_excluded(data_dir):
    bars = ManualFileProvider(data_dir).daily_bars(
        "TEST", date(2026, 3, 10), date(2026, 3, 10)
    )
    assert len(bars) == 1
    assert bars[0].session_date == date(2026, 3, 10)


def test_missing_bar_history_is_refused(data_dir):
    with pytest.raises(MarketDataError, match="no bar history"):
        ManualFileProvider(data_dir).daily_bars(
            "GHOST", date(2026, 3, 1), date(2026, 3, 11)
        )


def test_a_bar_file_missing_columns_is_refused(tmp_path):
    bars = tmp_path / BAR_DIRECTORY
    bars.mkdir()
    (bars / "TEST.csv").write_text("session_date,close\n2026-03-09,10\n", encoding="utf-8")
    with pytest.raises(MarketDataError, match="missing column"):
        ManualFileProvider(tmp_path).daily_bars("TEST", date(2026, 3, 1), date(2026, 3, 11))


def test_an_unparseable_bar_date_is_refused(tmp_path):
    bars = tmp_path / BAR_DIRECTORY
    bars.mkdir()
    (bars / "TEST.csv").write_text(
        "session_date,open,high,low,close,volume\n09/03/2026,10,10,10,10,1\n",
        encoding="utf-8",
    )
    with pytest.raises(MarketDataError, match="must be ISO"):
        ManualFileProvider(tmp_path).daily_bars("TEST", date(2026, 3, 1), date(2026, 3, 11))


def test_an_unparseable_bar_price_is_refused(tmp_path):
    bars = tmp_path / BAR_DIRECTORY
    bars.mkdir()
    (bars / "TEST.csv").write_text(
        "session_date,open,high,low,close,volume\n2026-03-09,10,ten,10,10,1\n",
        encoding="utf-8",
    )
    with pytest.raises(MarketDataError, match="unusable"):
        ManualFileProvider(tmp_path).daily_bars("TEST", date(2026, 3, 1), date(2026, 3, 11))


def test_instruments_default_to_empty_when_absent(data_dir):
    assert ManualFileProvider(data_dir).instruments() == []
