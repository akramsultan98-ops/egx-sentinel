"""The operator CLI, exercised against a real database.

These call the command functions directly rather than through ``main`` so the
clock and the connection stay injectable and the suite stays deterministic.
"""

import json
from decimal import Decimal

import pytest

from egx_engine.cli import (
    NO_MARKET_DATA,
    PROVIDER_UNHEALTHY,
    _encode,
    default_universe_file,
    ingest_command,
    load_universe_command,
    scan_command,
)
from egx_engine.db.repository import Repository
from egx_engine.providers import BAR_DIRECTORY, SNAPSHOT_FILE, ManualFileProvider
from egx_engine.provider import UnconfiguredProvider
from egx_engine.universe import UniverseError

from conftest import NOW, make_bars, make_snapshot

pytestmark = pytest.mark.integration

HEADER = (
    "instrument_id,ticker,name,asset_type,sector,telda_available,telda_verified_on\n"
)


@pytest.fixture
def verified_universe_file(tmp_path):
    path = tmp_path / "universe.csv"
    path.write_text(
        HEADER + "TEST,TEST,Test Instrument,EQUITY,Banks,true,2026-03-01\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def manual_dir(tmp_path):
    """An operator data directory holding one quote and 20 sessions of history."""
    directory = tmp_path / "market"
    directory.mkdir()

    snapshot = make_snapshot(source="manual").model_dump(mode="json")
    (directory / SNAPSHOT_FILE).write_text(json.dumps([snapshot]), encoding="utf-8")

    bars = directory / BAR_DIRECTORY
    bars.mkdir()
    rows = ["session_date,open,high,low,close,volume"]
    for bar in make_bars(20, spread="0.20"):
        rows.append(
            f"{bar.session_date},{bar.open},{bar.high},{bar.low},{bar.close},{bar.volume}"
        )
    (bars / "TEST.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    return directory


@pytest.fixture
def provider(manual_dir):
    return ManualFileProvider(manual_dir)


# --- load-universe --------------------------------------------------------


def test_shipped_universe_loads_but_enables_nothing(conn):
    result = load_universe_command(conn, default_universe_file())

    assert result["loaded"] > 0
    assert result["telda_available"] == 0
    assert result["telda_available_tickers"] == []
    assert Repository(conn).get_universe(telda_available=True) == []


def test_a_verified_file_enables_its_instruments(conn, verified_universe_file):
    result = load_universe_command(conn, verified_universe_file)

    assert result["telda_available_tickers"] == ["TEST"]
    row = Repository(conn).get_instrument("TEST")
    assert row["telda_available"] is True
    assert row["telda_verified_at"] is not None


def test_loading_is_idempotent(conn, verified_universe_file):
    load_universe_command(conn, verified_universe_file)
    load_universe_command(conn, verified_universe_file)

    assert len(Repository(conn).get_universe()) == 1


# --- ingest ---------------------------------------------------------------


def test_ingest_stores_bars(conn, provider, instrument):
    result = ingest_command(conn, provider, today=NOW.date())

    assert result["results"] == [{"ticker": "TEST", "bars": 20, "error": None}]
    assert len(Repository(conn).get_daily_bars("TEST", source="manual")) == 20


def test_ingest_reports_a_missing_series_without_failing_the_run(conn, provider, repo):
    repo.upsert_instrument(
        instrument_id="GHOST", ticker="GHOST", name="Ghost",
        source="fixture", source_updated_at=NOW,
    )
    conn.commit()

    result = ingest_command(conn, provider, today=NOW.date())

    by_ticker = {r["ticker"]: r for r in result["results"]}
    assert by_ticker["GHOST"]["bars"] == 0
    assert "no bar history" in by_ticker["GHOST"]["error"]


def test_ingest_covers_instruments_that_are_not_tradeable(conn, provider, repo):
    """History is a market fact; storing it implies no permission to buy."""
    repo.upsert_instrument(
        instrument_id="TEST", ticker="TEST", name="Test Instrument",
        source="fixture", source_updated_at=NOW, telda_available=False,
    )
    conn.commit()

    result = ingest_command(conn, provider, today=NOW.date())
    assert result["results"][0]["bars"] == 20


def test_an_unregistered_ticker_is_refused(conn, provider, instrument):
    with pytest.raises(UniverseError, match="not registered"):
        ingest_command(conn, provider, tickers=["GHOST"], today=NOW.date())


# --- scan -----------------------------------------------------------------


def test_scan_produces_a_persisted_buy(conn, provider, portfolio_id):
    ingest_command(conn, provider, today=NOW.date())

    result = scan_command(conn, provider, portfolio_id=portfolio_id, now=NOW)

    assert len(result["decisions"]) == 1
    decision = result["decisions"][0]
    assert decision["action"] == "BUY"
    assert decision["persisted"] is True
    assert decision["is_actionable"] is True
    assert decision["shares"] > 0
    assert decision["stop_loss"] < decision["entry"] < decision["target"]
    assert decision["risk_plan_id"] is not None
    assert result["liquidity_gate"] == "traded_value"


def test_scan_refuses_without_history(conn, provider, portfolio_id):
    """No bars ingested, so no stop can be derived from volatility."""
    result = scan_command(conn, provider, portfolio_id=portfolio_id, now=NOW)

    decision = result["decisions"][0]
    assert decision["action"] == "NO_TRADE"
    assert decision["reason"] == "INSUFFICIENT_HISTORY"
    assert decision["persisted"] is True


def test_scan_skips_instruments_outside_the_telda_universe(conn, provider, repo, portfolio_id):
    repo.upsert_instrument(
        instrument_id="TEST", ticker="TEST", name="Test Instrument",
        source="fixture", source_updated_at=NOW, telda_available=False,
    )
    conn.commit()

    result = scan_command(conn, provider, portfolio_id=portfolio_id, now=NOW)
    assert result["decisions"] == []


def test_scan_reports_a_missing_quote(conn, provider, repo, portfolio_id):
    repo.upsert_instrument(
        instrument_id="OTHER", ticker="OTHER", name="Other",
        source="fixture", source_updated_at=NOW,
        telda_available=True, telda_verified_at=NOW,
    )
    conn.commit()

    result = scan_command(conn, provider, portfolio_id=portfolio_id, now=NOW)

    by_ticker = {d["ticker"]: d for d in result["decisions"]}
    assert by_ticker["OTHER"]["reason"] == NO_MARKET_DATA
    assert by_ticker["OTHER"]["persisted"] is False
    assert by_ticker["OTHER"]["is_actionable"] is False


def test_an_unhealthy_provider_decides_nothing(conn, portfolio_id):
    result = scan_command(
        conn, UnconfiguredProvider(), portfolio_id=portfolio_id, now=NOW
    )

    assert result["reason"] == PROVIDER_UNHEALTHY
    assert result["decisions"] == []


def test_scan_output_is_json_serialisable(conn, provider, portfolio_id):
    ingest_command(conn, provider, today=NOW.date())
    result = scan_command(conn, provider, portfolio_id=portfolio_id, now=NOW)

    rendered = json.dumps(result, default=_encode)
    assert '"action": "BUY"' in rendered


def test_decimals_are_encoded_as_strings_not_floats():
    """A float round-trip would corrupt a price on its way out."""
    assert _encode(Decimal("10.1")) == "10.1"
    assert json.dumps({"p": Decimal("0.1")}, default=_encode) == '{"p": "0.1"}'


def test_encoder_refuses_what_it_cannot_represent():
    with pytest.raises(TypeError):
        _encode(object())
