"""Risk-engine tests: every gate, plus the fail-closed paths."""

from decimal import Decimal

import pytest

from egx_engine.config import RiskPolicy
from egx_engine.liquidity import TradedValueLiquidityGate, UnconfiguredLiquidityGate
from egx_engine.models import PortfolioState
from egx_engine.risk import DATA_NOT_VERIFIED_NO_TRADE, build_risk_plan
from egx_engine.validator import ValidationResult, validate_snapshot

from conftest import NOW, make_snapshot


def validated(**overrides):
    snap = make_snapshot(**overrides)
    result = validate_snapshot(snap, now=NOW)
    assert result.valid, result.reasons
    return result


def plan(validation=None, **kwargs):
    kwargs.setdefault("stop_loss", Decimal("9.50"))
    kwargs.setdefault("target", Decimal("11"))
    return build_risk_plan(validation or validated(), **kwargs)


# --- risk per trade -----------------------------------------------------


def test_position_size_respects_risk_budget(portfolio, zero_fee_policy, liquid_gate):
    """The 1.5%-of-equity rule is preserved exactly."""
    result = plan(portfolio=portfolio, policy=zero_fee_policy, liquidity_gate=liquid_gate)

    assert result.action == "BUY"
    assert result.shares == 150
    assert result.risk_egp == Decimal("75.00")
    assert result.risk_reward == Decimal("2")
    assert result.reason == "RISK_GATE_PASSED"


def test_risk_never_exceeds_the_budget_across_stop_widths(
    portfolio, zero_fee_policy, liquid_gate
):
    budget = portfolio.equity_egp * zero_fee_policy.risk_per_trade_fraction
    for stop in ["9.9", "9.75", "9.5", "9.1", "8"]:
        stop_loss = Decimal(stop)
        target = Decimal("10") + (Decimal("10") - stop_loss) * 3
        result = plan(
            stop_loss=stop_loss,
            target=target,
            portfolio=portfolio,
            policy=zero_fee_policy,
            liquidity_gate=liquid_gate,
        )
        assert result.risk_egp <= budget, stop


def test_risk_budget_too_small_for_one_share(zero_fee_policy, liquid_gate):
    tiny = PortfolioState(equity_egp=Decimal("100"), cash_egp=Decimal("5000"))
    result = plan(
        stop_loss=Decimal("5"),
        target=Decimal("25"),
        portfolio=tiny,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "RISK_BUDGET_TOO_SMALL"


def test_entry_defaults_to_validated_last_price(portfolio, zero_fee_policy, liquid_gate):
    result = plan(portfolio=portfolio, policy=zero_fee_policy, liquidity_gate=liquid_gate)
    assert result.entry == Decimal("10")
    assert result.snapshot_source == "fixture"
    assert result.snapshot_timestamp_utc == NOW


# --- concentration ------------------------------------------------------


def test_concentration_cap_binds_before_risk_budget(
    portfolio, zero_fee_policy, liquid_gate
):
    """A tight stop would justify far more notional than 30% of equity."""
    result = plan(
        stop_loss=Decimal("9.9"),
        target=Decimal("10.3"),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "BUY"
    assert result.shares == 150
    assert result.position_value_egp == Decimal("1500.00")
    assert result.concentration_fraction == Decimal("0.30")
    assert result.risk_egp < portfolio.equity_egp * zero_fee_policy.risk_per_trade_fraction


def test_concentration_never_exceeded(portfolio, zero_fee_policy, liquid_gate):
    limit = portfolio.equity_egp * zero_fee_policy.max_position_concentration_fraction
    for stop in ["9.95", "9.9", "9.8", "9.5"]:
        stop_loss = Decimal(stop)
        target = Decimal("10") + (Decimal("10") - stop_loss) * 3
        result = plan(
            stop_loss=stop_loss,
            target=target,
            portfolio=portfolio,
            policy=zero_fee_policy,
            liquidity_gate=liquid_gate,
        )
        assert result.position_value_egp <= limit, stop


def test_concentration_limit_smaller_than_one_share(zero_fee_policy, liquid_gate):
    small = PortfolioState(equity_egp=Decimal("20"), cash_egp=Decimal("5000"))
    result = plan(
        stop_loss=Decimal("9.99"),
        target=Decimal("10.05"),
        portfolio=small,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "CONCENTRATION_LIMIT_TOO_SMALL"


# --- cash ---------------------------------------------------------------


def test_cash_limits_position_size(zero_fee_policy, liquid_gate):
    poor = PortfolioState(equity_egp=Decimal("5000"), cash_egp=Decimal("500"))
    result = plan(portfolio=poor, policy=zero_fee_policy, liquidity_gate=liquid_gate)
    assert result.action == "BUY"
    assert result.shares == 50
    assert result.position_value_egp <= poor.cash_egp


def test_insufficient_cash_is_no_trade(zero_fee_policy, liquid_gate):
    broke = PortfolioState(equity_egp=Decimal("5000"), cash_egp=Decimal("5"))
    result = plan(portfolio=broke, policy=zero_fee_policy, liquidity_gate=liquid_gate)
    assert result.action == "NO_TRADE"
    assert result.reason == "INSUFFICIENT_CASH"


# --- price levels -------------------------------------------------------


def test_stop_above_entry_is_rejected(portfolio, zero_fee_policy, liquid_gate):
    result = plan(
        stop_loss=Decimal("10.5"),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "STOP_MUST_BE_BELOW_ENTRY"


def test_non_positive_stop_is_rejected(portfolio, zero_fee_policy, liquid_gate):
    result = plan(
        stop_loss=Decimal("0"),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "INVALID_PRICE_LEVELS"


def test_target_below_entry_is_rejected(portfolio, zero_fee_policy, liquid_gate):
    result = plan(
        target=Decimal("9.75"),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "TARGET_MUST_EXCEED_ENTRY"


def test_risk_reward_below_minimum_is_rejected(portfolio, zero_fee_policy, liquid_gate):
    result = plan(
        stop_loss=Decimal("9"),
        target=Decimal("11"),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "RISK_REWARD_BELOW_MINIMUM"
    assert result.risk_reward_gross == Decimal("1")


def test_risk_reward_exactly_two_is_allowed(portfolio, zero_fee_policy, liquid_gate):
    result = plan(portfolio=portfolio, policy=zero_fee_policy, liquidity_gate=liquid_gate)
    assert result.action == "BUY"
    assert result.risk_reward == Decimal("2")


# --- entry anchoring ----------------------------------------------------


def test_entry_far_from_market_price_is_rejected(portfolio, zero_fee_policy, liquid_gate):
    """An invented entry cannot reach sizing even with a validated snapshot."""
    result = plan(
        entry=Decimal("12"),
        stop_loss=Decimal("11"),
        target=Decimal("15"),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "ENTRY_NOT_ANCHORED_TO_MARKET"


def test_entry_within_tolerance_is_accepted(portfolio, zero_fee_policy, liquid_gate):
    result = plan(
        entry=Decimal("10.1"),
        stop_loss=Decimal("9.6"),
        target=Decimal("11.1"),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "BUY"
    assert result.entry == Decimal("10.1")


# --- fees ---------------------------------------------------------------


def test_fees_reduce_position_size(portfolio, zero_fee_policy, liquid_gate):
    with_fees = plan(
        target=Decimal("12"), portfolio=portfolio, liquidity_gate=liquid_gate
    )
    without_fees = plan(
        target=Decimal("12"),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert with_fees.action == without_fees.action == "BUY"
    assert with_fees.shares == 136
    assert without_fees.shares == 150
    assert with_fees.fees_egp > 0
    assert with_fees.risk_egp <= Decimal("75")


def test_fees_can_invalidate_a_marginal_risk_reward(portfolio, liquid_gate):
    """Gross R/R of exactly 2 does not survive round-trip costs."""
    result = plan(portfolio=portfolio, liquidity_gate=liquid_gate)
    assert result.action == "NO_TRADE"
    assert result.reason == "RISK_REWARD_BELOW_MINIMUM_AFTER_FEES"
    assert result.risk_reward_gross == Decimal("2")
    assert result.risk_reward < Decimal("2")


def test_minimum_fee_is_applied(portfolio, liquid_gate):
    policy = RiskPolicy(fee_rate_fraction=Decimal("0.0025"), min_fee_egp=Decimal("20"))
    result = plan(
        target=Decimal("13"),
        portfolio=portfolio,
        policy=policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "BUY"
    assert result.shares == 70
    assert result.fees_egp == Decimal("40")
    assert result.risk_egp <= Decimal("75")


def test_fees_are_included_in_reported_risk(portfolio, liquid_gate):
    result = plan(target=Decimal("12"), portfolio=portfolio, liquidity_gate=liquid_gate)
    price_only_risk = Decimal("0.5") * result.shares
    assert result.risk_egp == price_only_risk + result.fees_egp


# --- liquidity ----------------------------------------------------------


def test_liquidity_gate_defaults_to_fail_closed(portfolio, zero_fee_policy):
    """No gate supplied means NO_TRADE, never an unchecked BUY."""
    result = plan(portfolio=portfolio, policy=zero_fee_policy)
    assert result.action == "NO_TRADE"
    assert result.reason == "LIQUIDITY_NOT_VERIFIED"


def test_explicit_unconfigured_gate_fails_closed(portfolio, zero_fee_policy):
    result = plan(
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=UnconfiguredLiquidityGate(),
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "LIQUIDITY_NOT_VERIFIED"


def test_missing_traded_value_fails_closed(portfolio, zero_fee_policy):
    result = plan(
        validation=validated(traded_value_egp=None),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=TradedValueLiquidityGate(),
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "LIQUIDITY_DATA_UNAVAILABLE"


def test_liquidity_caps_position_size(portfolio, zero_fee_policy):
    result = plan(
        validation=validated(traded_value_egp=Decimal("100000")),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=TradedValueLiquidityGate(Decimal("0.01")),
    )
    assert result.action == "BUY"
    assert result.shares == 100
    assert result.position_value_egp == Decimal("1000")


def test_illiquid_instrument_is_no_trade(portfolio, zero_fee_policy):
    result = plan(
        validation=validated(traded_value_egp=Decimal("100")),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=TradedValueLiquidityGate(Decimal("0.01")),
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "LIQUIDITY_INSUFFICIENT"


def test_minimum_traded_value_threshold(portfolio, zero_fee_policy):
    result = plan(
        validation=validated(traded_value_egp=Decimal("50000")),
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=TradedValueLiquidityGate(
            Decimal("0.01"), min_traded_value_egp=Decimal("1000000")
        ),
    )
    assert result.action == "NO_TRADE"
    assert result.reason == "LIQUIDITY_INSUFFICIENT"


# --- open positions -----------------------------------------------------


def test_max_open_positions_blocks_a_third(zero_fee_policy, liquid_gate):
    full = PortfolioState(
        equity_egp=Decimal("5000"), cash_egp=Decimal("5000"), open_positions=2
    )
    result = plan(portfolio=full, policy=zero_fee_policy, liquidity_gate=liquid_gate)
    assert result.action == "NO_TRADE"
    assert result.reason == "MAX_OPEN_POSITIONS_REACHED"


def test_one_open_position_still_allows_a_buy(zero_fee_policy, liquid_gate):
    one = PortfolioState(
        equity_egp=Decimal("5000"), cash_egp=Decimal("5000"), open_positions=1
    )
    result = plan(portfolio=one, policy=zero_fee_policy, liquidity_gate=liquid_gate)
    assert result.action == "BUY"


# --- validated vs unvalidated inputs ------------------------------------


def test_invalid_snapshot_fails_closed(portfolio, zero_fee_policy, liquid_gate):
    bad = validate_snapshot(
        make_snapshot(bid=Decimal("10.2"), ask=Decimal("10.1")), now=NOW
    )
    assert bad.status == "INVALID"
    result = plan(
        validation=bad,
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "NO_TRADE"
    assert result.reason == DATA_NOT_VERIFIED_NO_TRADE


def test_stale_snapshot_fails_closed(portfolio, zero_fee_policy, liquid_gate):
    stale = validate_snapshot(
        make_snapshot(freshness_seconds=900, source_timestamp=NOW), now=NOW
    )
    assert stale.valid is False
    result = plan(
        validation=stale,
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "NO_TRADE"
    assert result.reason == DATA_NOT_VERIFIED_NO_TRADE


def test_raw_snapshot_cannot_produce_a_plan(portfolio, zero_fee_policy, liquid_gate):
    with pytest.raises(TypeError):
        build_risk_plan(
            make_snapshot(),
            stop_loss=Decimal("9.5"),
            target=Decimal("11"),
            portfolio=portfolio,
            policy=zero_fee_policy,
            liquidity_gate=liquid_gate,
        )


def test_forged_validation_result_is_caught(portfolio, zero_fee_policy, liquid_gate):
    """A hand-built VALID verdict over an unstamped snapshot must not pass."""
    forged = ValidationResult(status="VALID", reasons=[], snapshot=make_snapshot())
    assert forged.snapshot.validation_status == "UNVERIFIED"
    result = plan(
        validation=forged,
        portfolio=portfolio,
        policy=zero_fee_policy,
        liquidity_gate=liquid_gate,
    )
    assert result.action == "NO_TRADE"
    assert result.reason == DATA_NOT_VERIFIED_NO_TRADE
