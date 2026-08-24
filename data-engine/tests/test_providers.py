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
    PayloadProvider,
    get_provider,
)
from egx_engine.settings import Settings, SettingsError
from egx_engine.validator import validate_snapshot

from conftest import NOW, make_bars, make_snapshot

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


# --- payload provider -----------------------------------------------------


def test_payload_provider_serves_supplied_quotes():
    provider = PayloadProvider([make_snapshot(source="google_sheet")])

    assert provider.name == "payload"
    assert provider.health() is True
    assert provider.snapshot(["TEST"])[0].last_price == Decimal("10")


def test_payload_provider_is_unhealthy_without_quotes():
    assert PayloadProvider([]).health() is False


def test_payload_provider_keeps_the_declared_source():
    """The transport is 'payload'; the provenance is whatever supplied it.

    A spreadsheet must never be able to masquerade as a live feed.
    """
    provider = PayloadProvider([make_snapshot(source="google_sheet")])
    assert provider.snapshot(["TEST"])[0].source == "google_sheet"
    assert provider.name == "payload"


def test_payload_provider_ignores_unrequested_tickers():
    provider = PayloadProvider([make_snapshot()])
    assert provider.snapshot(["OTHER"]) == []


def test_payload_provider_matching_ignores_case_and_padding():
    provider = PayloadProvider([make_snapshot()])
    assert len(provider.snapshot([" test "])) == 1


def test_payload_provider_serves_bars_in_range():
    series = make_bars(10, source="google_sheet")
    provider = PayloadProvider([make_snapshot()], {"TEST": series})

    everything = provider.daily_bars("TEST", date(2000, 1, 1), date(2100, 1, 1))
    assert len(everything) == 10
    assert everything == sorted(everything, key=lambda b: b.session_date)

    window = provider.daily_bars(
        "TEST", series[2].session_date, series[4].session_date
    )
    assert len(window) == 3


def test_payload_provider_refuses_history_it_was_not_given():
    provider = PayloadProvider([make_snapshot()])
    with pytest.raises(MarketDataError, match="no bar history supplied"):
        provider.daily_bars("TEST", date(2000, 1, 1), date(2100, 1, 1))


def test_payload_provider_snapshots_still_face_the_validator():
    """No shortcut: payload data is validated exactly like a vendor feed."""
    provider = PayloadProvider(
        [make_snapshot(source="google_sheet", freshness_seconds=99999)]
    )
    assert validate_snapshot(provider.snapshot(["TEST"])[0], now=NOW).valid is False
