"""Deterministic position sizing and risk gating.

Every BUY must survive, in order:

1. a snapshot that validated as ``VALID`` (otherwise ``DATA_NOT_VERIFIED_NO_TRADE``)
2. the maximum open-position count
3. price-level sanity (stop below entry, target above entry)
4. an entry anchored to the validated last traded price
5. gross reward-to-risk
6. the liquidity gate
7. sizing against the risk budget, available cash, the concentration cap, and
   the liquidity ceiling — all fee-aware
8. reward-to-risk again, net of estimated fees

No gate is skippable and no path produces a BUY from prices that did not come
with a validated snapshot. Cash / ``NO_TRADE`` is always an acceptable outcome.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR

from .config import DEFAULT_RISK_POLICY, RiskPolicy
from .liquidity import LiquidityGate, UnconfiguredLiquidityGate
from .models import PortfolioState, RiskPlan
from .validator import ValidationResult

DATA_NOT_VERIFIED_NO_TRADE = "DATA_NOT_VERIFIED_NO_TRADE"


def _floor_div(numerator: Decimal, denominator: Decimal) -> int:
    if denominator <= 0:
        return 0
    if numerator <= 0:
        return 0
    return int((numerator / denominator).to_integral_value(rounding=ROUND_FLOOR))


def _largest_satisfying(upper_bound: int, fits) -> int:
    """Largest ``n`` in ``[0, upper_bound]`` with ``fits(n)`` true.

    ``fits`` must be monotonically decreasing (true for every cost function used
    here, since cost grows with share count). Binary search keeps sizing exact
    and deterministic rather than iteratively guessing.
    """
    if upper_bound <= 0 or not fits(1):
        return 0
    low, high = 1, upper_bound
    while low < high:
        mid = (low + high + 1) // 2
        if fits(mid):
            low = mid
        else:
            high = mid - 1
    return low


def build_risk_plan(
    validation: ValidationResult,
    *,
    stop_loss: Decimal,
    target: Decimal,
    portfolio: PortfolioState,
    entry: Decimal | None = None,
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
    liquidity_gate: LiquidityGate | None = None,
) -> RiskPlan:
    """Build a deterministic risk plan from a *validated* market snapshot.

    Args:
        validation: result of :func:`egx_engine.validator.validate_snapshot`.
            Anything other than ``VALID`` fails closed.
        stop_loss: protective stop, must sit below the entry.
        target: profit objective, must sit above the entry.
        portfolio: equity, cash, and open-position count read from PostgreSQL.
        entry: optional explicit entry. Defaults to the validated last price and
            must stay within ``policy.max_entry_deviation_fraction`` of it.
        policy: risk limits (see :mod:`egx_engine.config`).
        liquidity_gate: defaults to the fail-closed
            :class:`~egx_engine.liquidity.UnconfiguredLiquidityGate`.
    """
    if not isinstance(validation, ValidationResult):
        raise TypeError(
            "build_risk_plan requires a ValidationResult; raw prices and raw "
            "snapshots cannot produce a risk plan"
        )

    snapshot = validation.snapshot
    ticker = snapshot.ticker

    def no_trade(reason: str, **fields) -> RiskPlan:
        return RiskPlan(
            ticker=ticker,
            action="NO_TRADE",
            reason=reason,
            snapshot_source=snapshot.source,
            snapshot_timestamp_utc=snapshot.timestamp_utc,
            **fields,
        )

    # 1. Validated facts only.
    if not validation.valid or snapshot.validation_status != "VALID":
        return no_trade(DATA_NOT_VERIFIED_NO_TRADE)

    # 2. Portfolio-level gate.
    if portfolio.open_positions >= policy.max_open_positions:
        return no_trade("MAX_OPEN_POSITIONS_REACHED")

    # 3. Price-level sanity.
    entry = snapshot.last_price if entry is None else entry
    if entry <= 0 or stop_loss <= 0 or target <= 0:
        return no_trade("INVALID_PRICE_LEVELS")
    if stop_loss >= entry:
        return no_trade("STOP_MUST_BE_BELOW_ENTRY", entry=entry, stop_loss=stop_loss)
    if target <= entry:
        return no_trade("TARGET_MUST_EXCEED_ENTRY", entry=entry, target=target)

    # 4. The entry must be anchored to the validated market price, so an
    #    invented or stale price cannot slip in through the `entry` argument.
    deviation = abs(entry - snapshot.last_price) / snapshot.last_price
    if deviation > policy.max_entry_deviation_fraction:
        return no_trade(
            "ENTRY_NOT_ANCHORED_TO_MARKET",
            entry=entry,
            stop_loss=stop_loss,
            target=target,
        )

    risk_per_share = entry - stop_loss
    reward_per_share = target - entry
    gross_rr = reward_per_share / risk_per_share

    levels = {"entry": entry, "stop_loss": stop_loss, "target": target}

    # 5. Reward-to-risk before fees; fees can only make this worse.
    if gross_rr < policy.min_risk_reward:
        return no_trade("RISK_REWARD_BELOW_MINIMUM", risk_reward_gross=gross_rr, **levels)

    # 6. Liquidity is a hard gate and defaults to fail-closed.
    gate = liquidity_gate if liquidity_gate is not None else UnconfiguredLiquidityGate()
    assessment = gate.assess(snapshot)
    if not assessment.ok or assessment.max_position_value_egp is None:
        return no_trade(assessment.reason, risk_reward_gross=gross_rr, **levels)

    # 7. Fee-aware sizing. Each constraint is evaluated independently so the
    #    binding one can be named in the NO_TRADE reason.
    def fee(notional: Decimal) -> Decimal:
        return max(policy.min_fee_egp, notional * policy.fee_rate_fraction)

    def total_risk(shares: int) -> Decimal:
        n = Decimal(shares)
        return (
            risk_per_share * n
            + fee(entry * n)          # commission paid on entry
            + fee(stop_loss * n)      # commission paid exiting at the stop
        )

    def total_cost(shares: int) -> Decimal:
        n = Decimal(shares)
        return entry * n + fee(entry * n)

    risk_budget = portfolio.equity_egp * policy.risk_per_trade_fraction
    concentration_budget = portfolio.equity_egp * policy.max_position_concentration_fraction

    shares_by_risk = _largest_satisfying(
        _floor_div(risk_budget, risk_per_share), lambda n: total_risk(n) <= risk_budget
    )
    shares_by_cash = _largest_satisfying(
        _floor_div(portfolio.cash_egp, entry), lambda n: total_cost(n) <= portfolio.cash_egp
    )
    shares_by_concentration = _floor_div(concentration_budget, entry)
    shares_by_liquidity = _floor_div(assessment.max_position_value_egp, entry)

    shares = min(
        shares_by_risk, shares_by_cash, shares_by_concentration, shares_by_liquidity
    )

    if shares <= 0:
        binding = min(
            (shares_by_risk, "RISK_BUDGET_TOO_SMALL"),
            (shares_by_cash, "INSUFFICIENT_CASH"),
            (shares_by_concentration, "CONCENTRATION_LIMIT_TOO_SMALL"),
            (shares_by_liquidity, "LIQUIDITY_INSUFFICIENT"),
            key=lambda pair: pair[0],
        )[1]
        return no_trade(binding, risk_reward_gross=gross_rr, **levels)

    n = Decimal(shares)
    position_value = entry * n
    entry_fee = fee(position_value)
    stop_fee = fee(stop_loss * n)
    target_fee = fee(target * n)

    risk_egp = risk_per_share * n + entry_fee + stop_fee
    reward_egp = reward_per_share * n - entry_fee - target_fee
    fees_egp = entry_fee + stop_fee

    # 8. Reward-to-risk net of fees. Fees never justify relaxing the gate.
    if reward_egp <= 0:
        return no_trade(
            "REWARD_ELIMINATED_BY_FEES",
            risk_reward_gross=gross_rr,
            fees_egp=fees_egp,
            **levels,
        )

    net_rr = reward_egp / risk_egp
    if net_rr < policy.min_risk_reward:
        return no_trade(
            "RISK_REWARD_BELOW_MINIMUM_AFTER_FEES",
            risk_reward=net_rr,
            risk_reward_gross=gross_rr,
            fees_egp=fees_egp,
            **levels,
        )

    # Defensive invariant: sizing must never exceed the risk budget.
    if risk_egp > risk_budget:  # pragma: no cover - unreachable by construction
        return no_trade("RISK_BUDGET_EXCEEDED", risk_reward_gross=gross_rr, **levels)

    return RiskPlan(
        ticker=ticker,
        action="BUY",
        entry=entry,
        stop_loss=stop_loss,
        target=target,
        shares=shares,
        position_value_egp=position_value,
        concentration_fraction=position_value / portfolio.equity_egp,
        fees_egp=fees_egp,
        risk_egp=risk_egp,
        reward_egp=reward_egp,
        risk_reward=net_rr,
        risk_reward_gross=gross_rr,
        snapshot_source=snapshot.source,
        snapshot_timestamp_utc=snapshot.timestamp_utc,
        reason="RISK_GATE_PASSED",
    )
