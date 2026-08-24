"""Deterministic ATR, stop, and target derivation. No database required."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from egx_engine.config import DEFAULT_RISK_POLICY, RiskPolicy
from egx_engine.levels import (
    ATR_NOT_POSITIVE,
    ATR_PERIOD,
    FEE_RATE_UNUSABLE,
    INSUFFICIENT_HISTORY,
    INVALID_ENTRY_PRICE,
    LEVELS_OK,
    STOP_NOT_POSITIVE,
    average_true_range,
    derive_levels,
    minimum_net_target,
)
from egx_engine.models import DailyBar
from egx_engine.risk import build_risk_plan
from egx_engine.validator import validate_snapshot

from conftest import NOW, make_bars, make_snapshot

ZERO_FEE = RiskPolicy(fee_rate_fraction=Decimal("0"), min_fee_egp=Decimal("0"))


def bar(day: int, *, high, low, close, open_=None) -> DailyBar:
    return DailyBar(
        ticker="TEST",
        session_date=date(2026, 3, 1) + timedelta(days=day),
        open=Decimal(open_ if open_ is not None else close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=1000,
        source="fixture",
    )


# --- ATR ------------------------------------------------------------------


def test_atr_needs_one_more_bar_than_the_period():
    assert average_true_range(make_bars(ATR_PERIOD), ATR_PERIOD) is None
    assert average_true_range(make_bars(ATR_PERIOD + 1), ATR_PERIOD) is not None


def test_atr_of_a_constant_range_is_that_range():
    atr = average_true_range(make_bars(20, spread="0.20"), ATR_PERIOD)
    assert atr == Decimal("0.20")


def test_true_range_includes_the_overnight_gap():
    """A gap beyond the session range must dominate high-minus-low."""
    bars = [
        bar(0, high="10", low="10", close="10"),
        bar(1, high="12", low="11.5", close="11.5"),
    ]
    # high-low is 0.5, but the gap from the previous close is 2.
    assert average_true_range(bars, 1) == Decimal("2")


def test_wilder_smoothing_is_not_a_simple_mean():
    bars = [
        bar(0, high="10", low="10", close="10"),
        bar(1, high="11", low="10", close="10.5"),    # TR 1.0
        bar(2, high="12", low="11", close="11.5"),    # TR 1.5 (gap)
        bar(3, high="12", low="11.5", close="11.75"),  # TR 0.5
    ]
    # Seed = mean(1.0, 1.5) = 1.25, then (1.25 * 1 + 0.5) / 2 = 0.875.
    # A simple mean of all three true ranges would be 1.0.
    assert average_true_range(bars, 2) == Decimal("0.875")


def test_atr_is_independent_of_input_order():
    bars = make_bars(20, spread="0.30")
    assert average_true_range(list(reversed(bars)), ATR_PERIOD) == average_true_range(
        bars, ATR_PERIOD
    )


def test_atr_rejects_a_nonsense_period():
    with pytest.raises(ValueError):
        average_true_range(make_bars(20), 0)


# --- derived levels -------------------------------------------------------


def test_stop_sits_two_atr_below_the_entry():
    plan = derive_levels(Decimal("10"), make_bars(20, spread="0.20"), policy=ZERO_FEE)

    assert plan.ok is True
    assert plan.reason == LEVELS_OK
    assert plan.atr == Decimal("0.20")
    assert plan.stop_loss == Decimal("9.600")
    assert plan.risk_per_share == Decimal("0.400")


def test_target_meets_the_minimum_reward_to_risk_without_fees():
    plan = derive_levels(Decimal("10"), make_bars(20, spread="0.20"), policy=ZERO_FEE)
    # entry + 2 * (entry - stop) = 10 + 2 * 0.4
    assert plan.target == Decimal("10.800")


def test_target_is_lifted_to_cover_fees():
    """A gross-only target would fail the net gate it exists to satisfy."""
    with_fees = derive_levels(Decimal("10"), make_bars(20, spread="0.20"))
    without = derive_levels(Decimal("10"), make_bars(20, spread="0.20"), policy=ZERO_FEE)

    assert with_fees.target > without.target
    assert with_fees.stop_loss == without.stop_loss


def test_derived_levels_survive_the_real_risk_engine():
    """The property that matters: derived levels actually produce a BUY.

    This is the regression guard for the fee-aware target. With a naive
    `entry + R * risk` target every derived setup would be rejected here as
    RISK_REWARD_BELOW_MINIMUM_AFTER_FEES.
    """
    snapshot = make_snapshot(last_price=Decimal("10"))
    levels = derive_levels(snapshot.last_price, make_bars(20, spread="0.20"))

    from egx_engine.liquidity import TradedValueLiquidityGate
    from egx_engine.models import PortfolioState

    plan = build_risk_plan(
        validate_snapshot(snapshot, now=NOW),
        stop_loss=levels.stop_loss,
        target=levels.target,
        portfolio=PortfolioState(equity_egp=Decimal("5000"), cash_egp=Decimal("5000")),
        policy=DEFAULT_RISK_POLICY,
        liquidity_gate=TradedValueLiquidityGate(Decimal("1")),
    )

    assert plan.action == "BUY"
    assert plan.reason == "RISK_GATE_PASSED"
    assert plan.risk_reward >= DEFAULT_RISK_POLICY.min_risk_reward
    assert plan.risk_egp <= Decimal("5000") * DEFAULT_RISK_POLICY.risk_per_trade_fraction


def test_levels_are_deterministic():
    first = derive_levels(Decimal("10"), make_bars(20, spread="0.20"))
    second = derive_levels(Decimal("10"), make_bars(20, spread="0.20"))
    assert (first.stop_loss, first.target, first.atr) == (
        second.stop_loss,
        second.target,
        second.atr,
    )


# --- refusals -------------------------------------------------------------


def test_short_history_refuses_rather_than_guessing():
    plan = derive_levels(Decimal("10"), make_bars(5))
    assert plan.ok is False
    assert plan.reason == INSUFFICIENT_HISTORY
    assert plan.stop_loss is None and plan.target is None


def test_no_history_at_all_refuses():
    plan = derive_levels(Decimal("10"), [])
    assert plan.ok is False
    assert plan.reason == INSUFFICIENT_HISTORY


def test_a_flat_series_gives_no_stop():
    plan = derive_levels(Decimal("10"), make_bars(20, spread="0"))
    assert plan.ok is False
    assert plan.reason == ATR_NOT_POSITIVE


def test_volatility_larger_than_the_price_refuses():
    plan = derive_levels(Decimal("0.30"), make_bars(20, spread="0.20"))
    assert plan.ok is False
    assert plan.reason == STOP_NOT_POSITIVE


def test_non_positive_entry_refuses():
    plan = derive_levels(Decimal("0"), make_bars(20))
    assert plan.ok is False
    assert plan.reason == INVALID_ENTRY_PRICE


def test_an_all_consuming_fee_rate_refuses():
    policy = RiskPolicy(fee_rate_fraction=Decimal("1"))
    plan = derive_levels(Decimal("10"), make_bars(20, spread="0.20"), policy=policy)
    assert plan.ok is False
    assert plan.reason == FEE_RATE_UNUSABLE


def test_minimum_net_target_is_none_when_fees_consume_everything():
    assert minimum_net_target(
        Decimal("10"), Decimal("9"), RiskPolicy(fee_rate_fraction=Decimal("1"))
    ) is None


def test_a_negative_multiplier_is_a_programming_error():
    with pytest.raises(ValueError):
        derive_levels(Decimal("10"), make_bars(20), multiplier=Decimal("0"))
