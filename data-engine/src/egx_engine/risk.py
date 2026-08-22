from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR

from .models import RiskPlan


def build_risk_plan(
    ticker: str,
    entry: Decimal,
    stop_loss: Decimal,
    target: Decimal,
    equity_egp: Decimal,
    cash_egp: Decimal,
    risk_pct: Decimal = Decimal("0.015"),
    min_rr: Decimal = Decimal("2"),
) -> RiskPlan:
    if entry <= 0 or stop_loss <= 0 or target <= 0:
        return RiskPlan(ticker=ticker, action="NO_TRADE", reason="INVALID_PRICE_LEVELS")
    if stop_loss >= entry:
        return RiskPlan(ticker=ticker, action="NO_TRADE", reason="STOP_MUST_BE_BELOW_ENTRY")
    if target <= entry:
        return RiskPlan(ticker=ticker, action="NO_TRADE", reason="TARGET_MUST_EXCEED_ENTRY")

    risk_per_share = entry - stop_loss
    reward_per_share = target - entry
    rr = reward_per_share / risk_per_share

    if rr < min_rr:
        return RiskPlan(
            ticker=ticker,
            action="NO_TRADE",
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            risk_reward=rr,
            reason="RISK_REWARD_BELOW_MINIMUM",
        )

    max_risk = equity_egp * risk_pct
    shares_by_risk = int((max_risk / risk_per_share).to_integral_value(rounding=ROUND_FLOOR))
    shares_by_cash = int((cash_egp / entry).to_integral_value(rounding=ROUND_FLOOR))
    shares = min(shares_by_risk, shares_by_cash)

    if shares <= 0:
        return RiskPlan(
            ticker=ticker,
            action="NO_TRADE",
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            risk_reward=rr,
            reason="INSUFFICIENT_CASH_OR_RISK_BUDGET",
        )

    return RiskPlan(
        ticker=ticker,
        action="BUY",
        entry=entry,
        stop_loss=stop_loss,
        target=target,
        shares=shares,
        risk_egp=risk_per_share * shares,
        reward_egp=reward_per_share * shares,
        risk_reward=rr,
        reason="RISK_GATE_PASSED",
    )
