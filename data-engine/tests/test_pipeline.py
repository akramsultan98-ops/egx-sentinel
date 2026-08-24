"""End-to-end decision pipeline: audit chain and fail-closed behaviour."""

from datetime import timedelta
from decimal import Decimal

import pytest

from egx_engine.config import DEFAULT_RISK_POLICY, RiskPolicy
from egx_engine.db.repository import Repository
from egx_engine.levels import INSUFFICIENT_HISTORY, derive_levels
from egx_engine.liquidity import TradedValueLiquidityGate, UnconfiguredLiquidityGate
from egx_engine.pipeline import (
    LEVELS_UNAVAILABLE,
    PERSISTENCE_UNAVAILABLE,
    evaluate_and_persist,
)
from egx_engine.risk import DATA_NOT_VERIFIED_NO_TRADE, build_risk_plan
from egx_engine.universe import NOT_IN_TELDA_UNIVERSE
from egx_engine.validator import validate_snapshot

from conftest import NOW, make_bars, make_snapshot

pytestmark = pytest.mark.integration

ZERO_FEE = RiskPolicy(fee_rate_fraction=Decimal("0"), min_fee_egp=Decimal("0"))
LIQUID = TradedValueLiquidityGate(Decimal("1"))


def run(conn, portfolio_id, *, snapshot=None, **kwargs):
    kwargs.setdefault("stop_loss", Decimal("9.50"))
    kwargs.setdefault("target", Decimal("11"))
    kwargs.setdefault("risk_policy", ZERO_FEE)
    kwargs.setdefault("liquidity_gate", LIQUID)
    kwargs.setdefault("now", NOW)
    return evaluate_and_persist(
        conn, snapshot or make_snapshot(), portfolio_id=portfolio_id, **kwargs
    )


# --- happy path ---------------------------------------------------------


def test_buy_is_persisted_and_actionable(conn, portfolio_id):
    record = run(conn, portfolio_id)

    assert record.persisted is True
    assert record.plan.action == "BUY"
    assert record.plan.shares == 150
    assert record.is_actionable is True
    assert record.snapshot_id and record.validation_result_id and record.risk_plan_id


def test_decision_survives_a_new_connection(conn, portfolio_id, migrated_database):
    """Committed means committed: another session can read the decision back."""
    record = run(conn, portfolio_id)

    from egx_engine.db.connection import connect

    with connect(migrated_database) as other:
        trail = Repository(other).get_decision_audit_trail(record.risk_plan_id)

    assert trail["decision"]["action"] == "BUY"
    assert trail["validation"]["status"] == "VALID"
    assert trail["source_data"]["last_price"] == Decimal("10.000000")


def test_audit_chain_is_complete(conn, portfolio_id):
    record = run(conn, portfolio_id)
    trail = Repository(conn).get_decision_audit_trail(record.risk_plan_id)

    assert trail["source_data"]["snapshot_id"] == record.snapshot_id
    assert trail["source_data"]["freshness_seconds"] == 10
    assert trail["validation"]["reasons"] == []
    assert trail["decision"]["liquidity_gate"] == "traded_value"
    assert trail["decision"]["equity_egp_at_decision"] == Decimal("5000.0000")


def test_pipeline_does_not_change_the_phase_0_decision(conn, portfolio_id):
    """The pipeline persists the Phase 0 verdict; it never alters it."""
    snapshot = make_snapshot()
    record = run(conn, portfolio_id, snapshot=snapshot)

    validation = validate_snapshot(snapshot, now=NOW)
    direct = build_risk_plan(
        validation,
        stop_loss=Decimal("9.50"),
        target=Decimal("11"),
        portfolio=Repository(conn).get_portfolio_state(portfolio_id),
        policy=ZERO_FEE,
        liquidity_gate=LIQUID,
    )

    assert record.plan.action == direct.action
    assert record.plan.shares == direct.shares
    assert record.plan.risk_egp == direct.risk_egp
    assert record.plan.reason == direct.reason


# --- rejections are audited too -----------------------------------------


def test_stale_data_is_recorded_as_a_rejection(conn, portfolio_id):
    record = run(
        conn,
        portfolio_id,
        snapshot=make_snapshot(
            freshness_seconds=5, source_timestamp=NOW - timedelta(hours=3)
        ),
    )

    assert record.persisted is True
    assert record.plan.action == "NO_TRADE"
    assert record.plan.reason == DATA_NOT_VERIFIED_NO_TRADE
    assert record.is_actionable is False

    trail = Repository(conn).get_decision_audit_trail(record.risk_plan_id)
    assert trail["validation"]["status"] == "INVALID"
    assert "FRESHNESS_MISREPORTED" in trail["validation"]["reasons"]


def test_unverified_liquidity_is_recorded_as_a_rejection(conn, portfolio_id):
    record = run(conn, portfolio_id, liquidity_gate=UnconfiguredLiquidityGate())

    assert record.persisted is True
    assert record.plan.reason == "LIQUIDITY_NOT_VERIFIED"
    assert record.is_actionable is False

    trail = Repository(conn).get_decision_audit_trail(record.risk_plan_id)
    assert trail["decision"]["liquidity_gate"] == "unconfigured"


# --- persistence failure must fail closed -------------------------------


def test_unknown_instrument_yields_no_trade(conn, portfolio_id):
    """A snapshot that cannot be stored must never come back as a BUY."""
    record = run(
        conn, portfolio_id, snapshot=make_snapshot(instrument_id="GHOST", ticker="GHOST")
    )

    assert record.persisted is False
    assert record.plan.action == "NO_TRADE"
    assert record.plan.reason == PERSISTENCE_UNAVAILABLE
    assert record.is_actionable is False
    assert record.risk_plan_id is None
    assert record.error


def test_failed_decision_leaves_nothing_behind(conn, portfolio_id):
    run(conn, portfolio_id, snapshot=make_snapshot(instrument_id="GHOST", ticker="GHOST"))

    with conn.cursor() as cur:
        for table in ("market_snapshots", "validation_results", "risk_plans"):
            cur.execute(f"SELECT count(*) FROM {table}")
            assert cur.fetchone()[0] == 0, table


def test_missing_portfolio_yields_no_trade(conn, instrument):
    record = run(conn, 999999)

    assert record.persisted is False
    assert record.plan.reason == PERSISTENCE_UNAVAILABLE
    assert record.is_actionable is False


def test_unknown_equity_yields_no_trade(conn, portfolio_id, repo):
    """An open position with no validated price makes equity unknown."""
    repo.record_execution(
        portfolio_id=portfolio_id, instrument_id="TEST", side="BUY", shares=100,
        execution_price=Decimal("10"), execution_time=NOW, idempotency_key="buy-1",
    )
    conn.commit()

    record = run(conn, portfolio_id)

    assert record.persisted is False
    assert record.plan.reason == PERSISTENCE_UNAVAILABLE
    assert record.is_actionable is False


def test_a_closed_connection_yields_no_trade(conn, portfolio_id, migrated_database):
    """Total persistence loss must still produce a safe answer, not an exception."""
    from egx_engine.db.connection import connect

    with connect(migrated_database) as doomed:
        doomed.close()
        record = run(doomed, portfolio_id)

    assert record.persisted is False
    assert record.plan.action == "NO_TRADE"
    assert record.plan.reason == PERSISTENCE_UNAVAILABLE
    assert record.is_actionable is False


def test_a_buy_is_never_actionable_without_persistence(conn, portfolio_id):
    """The property that matters: no unrecorded BUY ever reaches a caller."""
    good = run(conn, portfolio_id)
    assert good.plan.action == "BUY" and good.is_actionable

    broken = run(
        conn, portfolio_id, snapshot=make_snapshot(instrument_id="GHOST", ticker="GHOST")
    )
    assert broken.plan.action == "NO_TRADE" and not broken.is_actionable


# --- idempotent re-runs --------------------------------------------------


def test_rerunning_the_same_tick_does_not_duplicate_market_data(conn, portfolio_id):
    first = run(conn, portfolio_id)
    second = run(conn, portfolio_id)

    assert first.snapshot_id == second.snapshot_id
    # Each evaluation is its own audit record, but the source tick is stored once.
    assert first.validation_result_id != second.validation_result_id

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM market_snapshots")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM risk_plans")
        assert cur.fetchone()[0] == 2


# --- Phase 2: the Telda universe gate ------------------------------------


def withdraw_availability(conn, instrument_id="TEST"):
    Repository(conn).upsert_instrument(
        instrument_id=instrument_id, ticker=instrument_id, name="Test Instrument",
        source="fixture", source_updated_at=NOW, telda_available=False,
    )
    conn.commit()


def test_an_unavailable_instrument_is_refused(conn, portfolio_id):
    withdraw_availability(conn)

    record = run(conn, portfolio_id)

    assert record.plan.action == "NO_TRADE"
    assert record.plan.reason == NOT_IN_TELDA_UNIVERSE
    assert record.is_actionable is False


def test_a_universe_refusal_is_fully_audited(conn, portfolio_id):
    """A rejection must carry the same evidence chain as a BUY."""
    withdraw_availability(conn)

    record = run(conn, portfolio_id)
    assert record.persisted is True

    trail = Repository(conn).get_decision_audit_trail(record.risk_plan_id)
    assert trail["decision"]["reason"] == NOT_IN_TELDA_UNIVERSE
    assert trail["validation"]["status"] == "VALID"
    assert trail["source_data"]["snapshot_id"] == record.snapshot_id
    assert trail["decision"]["equity_egp_at_decision"] == Decimal("5000.0000")


def test_data_validity_outranks_the_universe_gate(conn, portfolio_id):
    """Both gates fail; the report names the more fundamental failure."""
    withdraw_availability(conn)

    record = run(
        conn,
        portfolio_id,
        snapshot=make_snapshot(
            freshness_seconds=5, source_timestamp=NOW - timedelta(hours=3)
        ),
    )

    assert record.plan.reason == DATA_NOT_VERIFIED_NO_TRADE


# --- Phase 2: derived levels ---------------------------------------------


def test_underivable_levels_are_recorded_as_a_rejection(conn, portfolio_id):
    record = run(
        conn,
        portfolio_id,
        stop_loss=None,
        target=None,
        levels_reason=INSUFFICIENT_HISTORY,
    )

    assert record.persisted is True
    assert record.plan.action == "NO_TRADE"
    assert record.plan.reason == INSUFFICIENT_HISTORY
    assert record.plan.shares == 0
    assert record.is_actionable is False

    trail = Repository(conn).get_decision_audit_trail(record.risk_plan_id)
    assert trail["decision"]["reason"] == INSUFFICIENT_HISTORY
    assert trail["validation"]["status"] == "VALID"


def test_missing_levels_without_a_reason_still_refuse(conn, portfolio_id):
    record = run(conn, portfolio_id, stop_loss=None, target=None)
    assert record.plan.reason == LEVELS_UNAVAILABLE
    assert record.is_actionable is False


def test_a_half_specified_setup_is_refused(conn, portfolio_id):
    """A stop without a target must never be sized."""
    record = run(conn, portfolio_id, target=None)
    assert record.plan.action == "NO_TRADE"
    assert record.plan.reason == LEVELS_UNAVAILABLE


def test_data_validity_outranks_the_levels_gate(conn, portfolio_id):
    record = run(
        conn,
        portfolio_id,
        stop_loss=None,
        target=None,
        levels_reason=INSUFFICIENT_HISTORY,
        snapshot=make_snapshot(
            freshness_seconds=5, source_timestamp=NOW - timedelta(hours=3)
        ),
    )

    assert record.plan.reason == DATA_NOT_VERIFIED_NO_TRADE


def test_derived_levels_produce_a_persisted_buy(conn, portfolio_id):
    """The whole Phase 2 chain: bars -> ATR -> levels -> risk -> committed BUY."""
    snapshot = make_snapshot(last_price=Decimal("10"))
    levels = derive_levels(snapshot.last_price, make_bars(20, spread="0.20"))
    assert levels.ok is True

    record = run(
        conn,
        portfolio_id,
        snapshot=snapshot,
        stop_loss=levels.stop_loss,
        target=levels.target,
        risk_policy=DEFAULT_RISK_POLICY,
    )

    assert record.plan.action == "BUY"
    assert record.is_actionable is True
    assert record.plan.stop_loss == levels.stop_loss
    assert record.plan.risk_reward >= DEFAULT_RISK_POLICY.min_risk_reward
