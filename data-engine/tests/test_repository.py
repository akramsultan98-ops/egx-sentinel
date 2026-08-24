"""Repository behaviour against a real PostgreSQL database."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest

from egx_engine.config import DEFAULT_DATA_POLICY, DEFAULT_RISK_POLICY
from egx_engine.db.errors import (
    DuplicateExecutionError,
    InsufficientSharesError,
    PersistenceError,
    PortfolioStateUnavailableError,
)
from egx_engine.db.repository import InsufficientCashError, Repository
from egx_engine.liquidity import TradedValueLiquidityGate
from egx_engine.models import PortfolioState
from egx_engine.risk import build_risk_plan
from egx_engine.universe import NOT_IN_TELDA_UNIVERSE, UniverseEntry, check_universe
from egx_engine.validator import validate_snapshot

from conftest import NOW, make_bars, make_snapshot

pytestmark = pytest.mark.integration


def store_decision(repo, portfolio_id, *, snapshot=None, **plan_kwargs):
    """Persist one full chain and return its ids."""
    snapshot = snapshot or make_snapshot()
    validation = validate_snapshot(snapshot, now=NOW)
    snapshot_id = repo.save_snapshot(validation.snapshot)
    validation_result_id = repo.save_validation_result(
        snapshot_id=snapshot_id,
        result=validation,
        data_policy=DEFAULT_DATA_POLICY,
        max_freshness_seconds=DEFAULT_DATA_POLICY.max_freshness_seconds,
        validated_at=NOW,
    )
    portfolio = repo.get_portfolio_state(portfolio_id)
    plan = build_risk_plan(
        validation,
        stop_loss=plan_kwargs.get("stop_loss", Decimal("9.50")),
        target=plan_kwargs.get("target", Decimal("12")),
        portfolio=portfolio,
        liquidity_gate=TradedValueLiquidityGate(Decimal("1")),
    )
    risk_plan_id = repo.save_risk_plan(
        plan=plan,
        validation_result_id=validation_result_id,
        instrument_id=snapshot.instrument_id,
        portfolio_id=portfolio_id,
        portfolio=portfolio,
        risk_policy=DEFAULT_RISK_POLICY,
        liquidity_gate="traded_value",
    )
    return snapshot_id, validation_result_id, risk_plan_id, plan


# --- successful persistence and retrieval -------------------------------


def test_snapshot_round_trip(repo, instrument, conn):
    snapshot = make_snapshot()
    snapshot_id = repo.save_snapshot(snapshot)
    conn.commit()

    loaded = repo.get_snapshot(snapshot_id)
    assert loaded.ticker == snapshot.ticker
    assert loaded.last_price == snapshot.last_price
    assert loaded.source == "fixture"
    assert loaded.timestamp_utc == NOW


def test_validation_result_round_trip(repo, instrument, conn):
    snapshot = make_snapshot(freshness_seconds=900, source_timestamp=NOW)
    validation = validate_snapshot(snapshot, now=NOW)
    assert validation.reasons

    snapshot_id = repo.save_snapshot(validation.snapshot)
    result_id = repo.save_validation_result(
        snapshot_id=snapshot_id,
        result=validation,
        data_policy=DEFAULT_DATA_POLICY,
        max_freshness_seconds=120,
        validated_at=NOW,
    )
    conn.commit()

    assert repo.get_validation_reasons(result_id) == validation.reasons


def test_risk_plan_round_trip(repo, portfolio_id, conn):
    _, _, risk_plan_id, plan = store_decision(repo, portfolio_id)
    conn.commit()

    loaded = repo.get_risk_plan(risk_plan_id)
    assert loaded.action == plan.action
    assert loaded.shares == plan.shares
    assert loaded.reason == plan.reason
    assert loaded.risk_egp == plan.risk_egp


def test_audit_trail_links_source_validation_and_decision(repo, portfolio_id, conn):
    snapshot_id, validation_result_id, risk_plan_id, plan = store_decision(
        repo, portfolio_id
    )
    conn.commit()

    trail = repo.get_decision_audit_trail(risk_plan_id)

    assert trail["source_data"]["snapshot_id"] == snapshot_id
    assert trail["source_data"]["source"] == "fixture"
    assert trail["validation"]["validation_result_id"] == validation_result_id
    assert trail["validation"]["status"] == "VALID"
    assert trail["decision"]["action"] == plan.action
    assert trail["decision"]["risk_policy"]["risk_per_trade_fraction"] == "0.015"
    assert trail["decision"]["equity_egp_at_decision"] == Decimal("5000.0000")


# --- idempotency and duplicate protection -------------------------------


def test_repeated_snapshot_delivery_is_idempotent(repo, instrument, conn):
    """An orchestrator retry must not inflate market history."""
    first = repo.save_snapshot(make_snapshot())
    second = repo.save_snapshot(make_snapshot())
    conn.commit()

    assert first == second
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM market_snapshots")
        assert cur.fetchone()[0] == 1


def test_duplicate_execution_is_rejected(repo, portfolio_id, conn):
    repo.record_execution(
        portfolio_id=portfolio_id,
        instrument_id="TEST",
        side="BUY",
        shares=10,
        execution_price=Decimal("10"),
        execution_time=NOW,
        idempotency_key="telegram-42",
    )
    conn.commit()

    with pytest.raises(DuplicateExecutionError):
        repo.record_execution(
            portfolio_id=portfolio_id,
            instrument_id="TEST",
            side="BUY",
            shares=10,
            execution_price=Decimal("10"),
            execution_time=NOW,
            idempotency_key="telegram-42",
        )
    conn.commit()

    # The duplicate must not have moved the portfolio a second time.
    assert len(repo.get_executions(portfolio_id)) == 1
    assert repo.get_position(portfolio_id, "TEST")["shares"] == 10
    with conn.cursor() as cur:
        cur.execute("SELECT cash_egp FROM portfolio WHERE portfolio_id = %s", (portfolio_id,))
        assert cur.fetchone()[0] == Decimal("4900.0000")


def test_connection_is_usable_after_a_duplicate(repo, portfolio_id, conn):
    """The savepoint must contain the failure, not poison the transaction."""
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=5,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="k1",
    )
    with pytest.raises(DuplicateExecutionError):
        repo.record_execution(
            portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=5,
            execution_price=Decimal("10"), execution_time=NOW, idempotency_key="k1",
        )

    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=5,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="k2",
    )
    conn.commit()
    assert repo.get_position(portfolio_id, "TEST")["shares"] == 10


# --- portfolio and position consistency ---------------------------------


def test_buy_moves_cash_and_opens_a_position(repo, portfolio_id, conn):
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=100,
        execution_price=Decimal("10"), execution_time=NOW, fees_egp=Decimal("2.5"),
        idempotency_key="buy-1",
    )
    conn.commit()

    position = repo.get_position(portfolio_id, "TEST")
    assert position["shares"] == 100
    assert position["average_entry"] == Decimal("10.000000")

    with conn.cursor() as cur:
        cur.execute("SELECT cash_egp FROM portfolio WHERE portfolio_id = %s", (portfolio_id,))
        assert cur.fetchone()[0] == Decimal("3997.5000")


def test_second_buy_averages_the_entry(repo, portfolio_id, conn):
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=100,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-1",
    )
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=100,
        execution_price=Decimal("12"), execution_time=NOW, idempotency_key="buy-2",
    )
    conn.commit()

    position = repo.get_position(portfolio_id, "TEST")
    assert position["shares"] == 200
    assert position["average_entry"] == Decimal("11.000000")


def test_sell_realises_pnl_and_closes_the_position(repo, portfolio_id, conn):
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=100,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-1",
    )
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="SELL", shares=100,
        execution_price=Decimal("11"), execution_time=NOW, idempotency_key="sell-1",
    )
    conn.commit()

    assert repo.get_position(portfolio_id, "TEST") is None

    with conn.cursor() as cur:
        cur.execute(
            "SELECT cash_egp, realized_pnl_egp FROM portfolio WHERE portfolio_id = %s",
            (portfolio_id,),
        )
        cash, realized = cur.fetchone()
        cur.execute(
            "SELECT shares, status, closed_at FROM portfolio_positions "
            "WHERE portfolio_id = %s",
            (portfolio_id,),
        )
        shares, status, closed_at = cur.fetchone()

    assert cash == Decimal("5100.0000")
    assert realized == Decimal("100.0000")
    # A fully sold position stays on record for audit rather than being deleted.
    assert (shares, status) == (0, "CLOSED")
    assert closed_at == NOW


def test_partial_sell_keeps_the_position_open(repo, portfolio_id, conn):
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=100,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-1",
    )
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="SELL", shares=40,
        execution_price=Decimal("11"), execution_time=NOW, idempotency_key="sell-1",
    )
    conn.commit()

    position = repo.get_position(portfolio_id, "TEST")
    assert position["shares"] == 60
    assert position["realized_pnl_egp"] == Decimal("40.0000")


def test_overselling_is_refused_and_changes_nothing(repo, portfolio_id, conn):
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=10,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-1",
    )
    conn.commit()

    with pytest.raises(InsufficientSharesError):
        repo.record_execution(
            portfolio_id=portfolio_id, instrument_id="TEST", side="SELL", shares=11,
            execution_price=Decimal("11"), execution_time=NOW, idempotency_key="sell-1",
        )
    conn.commit()

    assert repo.get_position(portfolio_id, "TEST")["shares"] == 10
    assert len(repo.get_executions(portfolio_id)) == 1


def test_selling_without_a_position_is_refused(repo, portfolio_id):
    with pytest.raises(InsufficientSharesError):
        repo.record_execution(
            portfolio_id=portfolio_id, instrument_id="TEST", side="SELL", shares=1,
            execution_price=Decimal("11"), execution_time=NOW, idempotency_key="sell-1",
        )


def test_buy_beyond_available_cash_is_refused(repo, portfolio_id, conn):
    with pytest.raises(InsufficientCashError):
        repo.record_execution(
            portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=1000,
            execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-big",
        )
    conn.commit()

    assert repo.get_executions(portfolio_id) == []
    with conn.cursor() as cur:
        cur.execute("SELECT cash_egp FROM portfolio WHERE portfolio_id = %s", (portfolio_id,))
        assert cur.fetchone()[0] == Decimal("5000.0000")


def test_one_open_position_per_instrument(repo, portfolio_id, conn):
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=10,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-1",
    )
    conn.commit()
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO portfolio_positions (portfolio_id, instrument_id, shares,"
                " average_entry, opened_at) VALUES (%s, 'TEST', 5, 10, %s)",
                (portfolio_id, NOW),
            )
    conn.rollback()


# --- portfolio state / fail-closed equity -------------------------------


def test_portfolio_state_for_a_cash_only_portfolio(repo, portfolio_id):
    state = repo.get_portfolio_state(portfolio_id)
    assert state == PortfolioState(
        equity_egp=Decimal("5000.0000"), cash_egp=Decimal("5000.0000"), open_positions=0
    )


def test_equity_uses_validated_prices(repo, portfolio_id, conn):
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=100,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-1",
    )
    validation = validate_snapshot(make_snapshot(last_price=Decimal("10.5")), now=NOW)
    repo.save_snapshot(validation.snapshot)
    conn.commit()

    state = repo.get_portfolio_state(portfolio_id)
    # 4000 cash + 100 shares at the validated 10.50
    assert state.equity_egp == Decimal("5050.0000")
    assert state.open_positions == 1


def test_unpriced_position_makes_equity_unavailable(repo, portfolio_id, conn):
    """Unknown equity must fail closed, not fall back to cost basis."""
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=100,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-1",
    )
    conn.commit()

    with pytest.raises(PortfolioStateUnavailableError):
        repo.get_portfolio_state(portfolio_id)


def test_invalid_snapshot_does_not_price_a_position(repo, portfolio_id, conn):
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=100,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-1",
    )
    rejected = validate_snapshot(
        make_snapshot(bid=Decimal("10.2"), ask=Decimal("10.1")), now=NOW
    )
    assert rejected.status == "INVALID"
    repo.save_snapshot(rejected.snapshot)
    conn.commit()

    with pytest.raises(PortfolioStateUnavailableError):
        repo.get_portfolio_state(portfolio_id)


def test_missing_portfolio_is_unavailable(repo):
    with pytest.raises(PortfolioStateUnavailableError):
        repo.get_portfolio_state(999999)


# --- transactions -------------------------------------------------------


def test_rollback_discards_the_whole_decision(repo, portfolio_id, conn):
    store_decision(repo, portfolio_id)
    conn.rollback()

    with conn.cursor() as cur:
        for table in ("market_snapshots", "validation_results", "risk_plans"):
            cur.execute(f"SELECT count(*) FROM {table}")
            assert cur.fetchone()[0] == 0, table


def test_rollback_discards_an_execution(repo, portfolio_id, conn):
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=100,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-1",
    )
    conn.rollback()

    assert repo.get_executions(portfolio_id) == []
    assert repo.get_position(portfolio_id, "TEST") is None
    with conn.cursor() as cur:
        cur.execute("SELECT cash_egp FROM portfolio WHERE portfolio_id = %s", (portfolio_id,))
        assert cur.fetchone()[0] == Decimal("5000.0000")


def test_unknown_instrument_is_refused(repo, portfolio_id, conn):
    """A snapshot for an unregistered instrument must not be storable."""
    with pytest.raises(PersistenceError):
        repo.save_snapshot(make_snapshot(instrument_id="GHOST", ticker="GHOST"))
    conn.rollback()


# --- constraints --------------------------------------------------------


def test_database_rejects_an_unknown_validation_status(repo, instrument, conn):
    snapshot_id = repo.save_snapshot(make_snapshot())
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "UPDATE market_snapshots SET validation_status = 'MAYBE' "
                "WHERE snapshot_id = %s",
                (snapshot_id,),
            )
    conn.rollback()


def test_database_rejects_a_valid_verdict_with_findings(repo, instrument, conn):
    snapshot_id = repo.save_snapshot(make_snapshot())
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO validation_results (snapshot_id, status, reasons,"
                " max_freshness_seconds, data_policy, validated_at)"
                " VALUES (%s, 'VALID', ARRAY['STALE_DATA'], 120, '{}'::jsonb, %s)",
                (snapshot_id, NOW),
            )
    conn.rollback()


def test_database_rejects_a_buy_without_shares(repo, portfolio_id, conn):
    _, validation_result_id, _, _ = store_decision(repo, portfolio_id)
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO risk_plans (validation_result_id, instrument_id,"
                " portfolio_id, action, reason, shares, equity_egp_at_decision,"
                " cash_egp_at_decision, open_positions_at_decision, risk_policy,"
                " liquidity_gate, engine_version)"
                " VALUES (%s, 'TEST', %s, 'BUY', 'RISK_GATE_PASSED', 0, 5000, 5000, 0,"
                " '{}'::jsonb, 'traded_value', 'test')",
                (validation_result_id, portfolio_id),
            )
    conn.rollback()


# --- timestamps ---------------------------------------------------------


def test_timestamps_are_stored_in_utc(repo, instrument, conn):
    cairo = timezone(timedelta(hours=2))
    snapshot = make_snapshot(
        timestamp_utc=NOW.astimezone(cairo), source_timestamp=NOW.astimezone(cairo)
    )
    snapshot_id = repo.save_snapshot(snapshot)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT timestamp_utc AT TIME ZONE 'UTC', source_timestamp AT TIME ZONE 'UTC'"
            " FROM market_snapshots WHERE snapshot_id = %s",
            (snapshot_id,),
        )
        stored_ts, stored_src = cur.fetchone()

    assert stored_ts == NOW.replace(tzinfo=None)
    assert stored_src == NOW.replace(tzinfo=None)
    assert repo.get_snapshot(snapshot_id).timestamp_utc == NOW


def test_naive_execution_time_is_refused(repo, portfolio_id):
    with pytest.raises(PersistenceError):
        repo.record_execution(
            portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=1,
            execution_price=Decimal("10"),
            execution_time=datetime(2026, 3, 11, 10, 0, 0),
            idempotency_key="naive",
        )


# --- Telda universe -----------------------------------------------------


def test_instrument_defaults_to_unavailable(repo, conn):
    repo.upsert_instrument(
        instrument_id="NEW", ticker="NEW", name="New Instrument",
        source="fixture", source_updated_at=NOW,
    )
    conn.commit()

    row = repo.get_instrument("NEW")
    assert row["telda_available"] is False
    assert row["telda_verified_at"] is None
    assert check_universe(row).reason == NOT_IN_TELDA_UNIVERSE


def test_unknown_instrument_reads_as_none(repo):
    assert repo.get_instrument("GHOST") is None


def test_availability_cannot_be_asserted_without_verification(repo, conn):
    """The database itself refuses an unverified availability claim."""
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.upsert_instrument(
            instrument_id="NEW", ticker="NEW", name="New Instrument",
            source="fixture", source_updated_at=NOW,
            telda_available=True,
        )
    conn.rollback()


def test_a_metadata_refresh_does_not_revoke_availability(repo, conn, instrument):
    """None means 'leave it alone', so a routine upsert cannot drop the gate."""
    repo.upsert_instrument(
        instrument_id="TEST", ticker="TEST", name="Renamed Instrument",
        source="fixture", source_updated_at=NOW,
    )
    conn.commit()

    row = repo.get_instrument("TEST")
    assert row["name"] == "Renamed Instrument"
    assert row["telda_available"] is True
    assert row["telda_verified_at"] == NOW


def test_availability_can_be_withdrawn_explicitly(repo, conn, instrument):
    repo.upsert_instrument(
        instrument_id="TEST", ticker="TEST", name="Test Instrument",
        source="fixture", source_updated_at=NOW, telda_available=False,
    )
    conn.commit()

    assert repo.get_instrument("TEST")["telda_available"] is False


def test_get_universe_filters_by_availability(repo, conn, instrument):
    repo.upsert_instrument(
        instrument_id="OTHER", ticker="OTHER", name="Other",
        source="fixture", source_updated_at=NOW,
    )
    conn.commit()

    assert {r["ticker"] for r in repo.get_universe()} == {"TEST", "OTHER"}
    assert [r["ticker"] for r in repo.get_universe(telda_available=True)] == ["TEST"]
    assert [r["ticker"] for r in repo.get_universe(telda_available=False)] == ["OTHER"]


def test_load_universe_writes_entries(repo, conn):
    entries = [
        UniverseEntry("AAA", "AAA", "Alpha", "EQUITY", "Banks", True, NOW),
        UniverseEntry("BBB", "BBB", "Beta", "EQUITY", None, False, None),
    ]
    assert repo.load_universe(entries, source="operator") == 2
    conn.commit()

    assert repo.get_instrument("AAA")["telda_available"] is True
    assert repo.get_instrument("BBB")["telda_available"] is False
    assert [r["ticker"] for r in repo.get_universe(telda_available=True)] == ["AAA"]


def test_load_universe_refuses_an_unverified_claim(repo, conn):
    entries = [UniverseEntry("AAA", "AAA", "Alpha", "EQUITY", None, True, None)]
    with pytest.raises(PersistenceError, match="without a verification date"):
        repo.load_universe(entries, source="operator")
    conn.rollback()


# --- daily bars ---------------------------------------------------------


def test_daily_bars_round_trip(repo, conn, instrument):
    assert repo.save_daily_bars("TEST", make_bars(5)) == 5
    conn.commit()

    stored = repo.get_daily_bars("TEST", source="fixture")
    assert len(stored) == 5
    assert stored == sorted(stored, key=lambda b: b.session_date)
    assert stored[0].ticker == "TEST"
    assert stored[0].close == Decimal("10.000000")


def test_saving_no_bars_is_a_no_op(repo, instrument):
    assert repo.save_daily_bars("TEST", []) == 0


def test_refetching_a_range_corrects_rather_than_duplicates(repo, conn, instrument):
    repo.save_daily_bars("TEST", make_bars(3, close="10"))
    conn.commit()
    repo.save_daily_bars("TEST", make_bars(3, close="11"))
    conn.commit()

    stored = repo.get_daily_bars("TEST", source="fixture")
    assert len(stored) == 3
    assert all(bar.close == Decimal("11.000000") for bar in stored)


def test_two_providers_keep_separate_series(repo, conn, instrument):
    repo.save_daily_bars("TEST", make_bars(3, source="fixture", close="10"))
    repo.save_daily_bars("TEST", make_bars(3, source="other", close="99"))
    conn.commit()

    assert len(repo.get_daily_bars("TEST", source="fixture")) == 3
    assert all(
        bar.close == Decimal("99.000000")
        for bar in repo.get_daily_bars("TEST", source="other")
    )


def test_limit_returns_the_most_recent_bars_oldest_first(repo, conn, instrument):
    repo.save_daily_bars("TEST", make_bars(10))
    conn.commit()

    everything = repo.get_daily_bars("TEST", source="fixture")
    recent = repo.get_daily_bars("TEST", source="fixture", limit=3)

    assert len(recent) == 3
    assert [b.session_date for b in recent] == [b.session_date for b in everything[-3:]]


def test_daily_bars_can_be_bounded_by_date(repo, conn, instrument):
    bars = make_bars(5)
    repo.save_daily_bars("TEST", bars)
    conn.commit()

    window = repo.get_daily_bars(
        "TEST", source="fixture", start=bars[1].session_date, end=bars[3].session_date
    )
    assert [b.session_date for b in window] == [b.session_date for b in bars[1:4]]


def test_bars_for_an_unregistered_instrument_are_refused(repo, conn):
    with pytest.raises(PersistenceError, match="could not save daily bars"):
        repo.save_daily_bars("GHOST", make_bars(2))
    conn.rollback()


# --- signals (AI research attached to a deterministic plan) --------------


def store_signal(repo, portfolio_id, **overrides):
    snapshot_id, _, risk_plan_id, _ = store_decision(repo, portfolio_id)
    params = dict(
        risk_plan_id=risk_plan_id,
        portfolio_id=portfolio_id,
        instrument_id="TEST",
        action="BUY",
        status="ACTIONABLE",
        snapshot_id=snapshot_id,
        model="openrouter/some-model",
        confidence=Decimal("0.82"),
        thesis="Loan growth and a widening margin.",
    )
    params.update(overrides)
    return repo.save_signal(**params), risk_plan_id


def test_signal_round_trip(repo, portfolio_id, conn):
    signal_id, risk_plan_id = store_signal(repo, portfolio_id)
    conn.commit()

    signal = repo.get_signal(signal_id)
    assert signal["risk_plan_id"] == risk_plan_id
    assert signal["model"] == "openrouter/some-model"
    assert signal["thesis"].startswith("Loan growth")
    assert signal["action"] == "BUY"
    assert signal["status"] == "ACTIONABLE"


def test_confidence_is_stored_as_a_percentage(repo, portfolio_id, conn):
    """Matches the percent-typed column convention in egx_engine.config."""
    signal_id, _ = store_signal(repo, portfolio_id, confidence=Decimal("0.82"))
    conn.commit()
    assert repo.get_signal(signal_id)["confidence"] == Decimal("82.00")


@pytest.mark.parametrize("bad", [Decimal("1.5"), Decimal("-0.1"), Decimal("82")])
def test_confidence_outside_zero_to_one_is_refused(repo, portfolio_id, conn, bad):
    with pytest.raises(PersistenceError, match="fraction between 0 and 1"):
        store_signal(repo, portfolio_id, confidence=bad)
    conn.rollback()


def test_research_cannot_be_recorded_without_a_risk_plan(repo, portfolio_id, conn):
    """A signal is a note on a decision; it can never stand alone."""
    with pytest.raises(PersistenceError, match="could not save signal"):
        repo.save_signal(
            risk_plan_id=999999, portfolio_id=portfolio_id, instrument_id="TEST",
            action="BUY", status="ACTIONABLE",
        )
    conn.rollback()


def test_a_signal_without_research_fields_is_allowed(repo, portfolio_id, conn):
    """A decision made with no AI input is still a decision."""
    signal_id, _ = store_signal(
        repo, portfolio_id, model=None, confidence=None, thesis=None
    )
    conn.commit()

    signal = repo.get_signal(signal_id)
    assert signal["model"] is None and signal["confidence"] is None


def test_unknown_signal_reads_as_none(repo):
    assert repo.get_signal(999999) is None
