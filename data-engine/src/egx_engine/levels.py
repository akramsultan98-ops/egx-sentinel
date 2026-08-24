"""Deterministic stop-loss and target derivation from daily bars.

``config/risk-policy.md`` forbids a BUY when a stop cannot be defined from
market structure or volatility. This module is the volatility half of that
rule, and it is what lets the system *originate* a proposal instead of only
scoring one a human handed it:

* Wilder's Average True Range over ``period`` completed daily bars.
* Stop placed ``multiplier`` ATR below the validated last traded price.
* Target placed at exactly the minimum reward-to-risk the risk policy demands.

Pure and deterministic — same bars in, same levels out, no clock and no I/O.
It returns an explicit refusal rather than a fallback whenever the inputs
cannot support a stop, because "we could not measure volatility" must produce
NO_TRADE, never a guessed stop.

Why the target formula is not simply ``entry + R * (entry - stop)``
-------------------------------------------------------------------
:mod:`egx_engine.risk` gates on reward-to-risk **net of fees**. A target set at
exactly ``R`` gross always lands below ``R`` net, so a naive formula would make
every derived setup fail the very gate it was built to satisfy. The target here
therefore solves for net reward-to-risk directly.

That solution assumes the proportional part of the fee model. If
``min_fee_egp`` is ever raised above zero the real fee can exceed the modelled
one, the derived target can fall short, and :mod:`egx_engine.risk` will reject
it. That is the correct direction to be wrong in: this module proposes, the
risk engine decides, and it re-checks net reward-to-risk itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Sequence

from .config import DEFAULT_RISK_POLICY, RiskPolicy
from .models import DailyBar

ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = Decimal("2")

# Prices are quoted to three decimals. Quantising in the conservative direction
# for each level keeps the derived setup honest after rounding: the stop only
# ever widens (smaller position) and the target only ever moves further away
# (reward-to-risk only ever improves).
PRICE_QUANTUM = Decimal("0.001")

LEVELS_OK = "LEVELS_OK"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
ATR_NOT_POSITIVE = "ATR_NOT_POSITIVE"
STOP_NOT_POSITIVE = "STOP_NOT_POSITIVE"
STOP_NOT_BELOW_ENTRY = "STOP_NOT_BELOW_ENTRY"
INVALID_ENTRY_PRICE = "INVALID_ENTRY_PRICE"
FEE_RATE_UNUSABLE = "FEE_RATE_UNUSABLE"


@dataclass(frozen=True)
class LevelPlan:
    """Derived levels, or an explicit refusal to derive them."""

    ok: bool
    reason: str
    stop_loss: Decimal | None = None
    target: Decimal | None = None
    atr: Decimal | None = None
    risk_per_share: Decimal | None = None


def average_true_range(
    bars: Sequence[DailyBar], period: int = ATR_PERIOD
) -> Decimal | None:
    """Wilder's ATR, or ``None`` when there is not enough history.

    ``period + 1`` bars are required: the first true range needs a previous
    close to measure the overnight gap against.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(bars) < period + 1:
        return None

    ordered = sorted(bars, key=lambda bar: bar.session_date)

    true_ranges: list[Decimal] = []
    for previous, current in zip(ordered, ordered[1:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )

    # Wilder's smoothing: a simple mean to seed, then a recursive average that
    # never fully forgets earlier volatility.
    atr = sum(true_ranges[:period], Decimal("0")) / Decimal(period)
    for true_range in true_ranges[period:]:
        atr = (atr * Decimal(period - 1) + true_range) / Decimal(period)

    return atr


def minimum_net_target(
    entry: Decimal, stop_loss: Decimal, policy: RiskPolicy
) -> Decimal | None:
    """Smallest target whose reward-to-risk clears ``policy.min_risk_reward`` net of fees.

    Solving ``reward >= R * risk`` per share, with ``f`` the proportional fee
    rate, ``E`` entry, ``S`` stop, ``R`` the required ratio::

        (T - E) - fE - fT  >=  R * [(E - S) + fE + fS]
        T * (1 - f)        >=  E(1 + f) + R * [(E - S) + f(E + S)]
        T                  >=  [E(1 + f) + R * ((E - S) + f(E + S))] / (1 - f)

    Share count cancels, so the result is independent of position size. Returns
    ``None`` when the fee rate makes the arithmetic meaningless.
    """
    fee = policy.fee_rate_fraction
    if fee >= 1:
        return None

    required = policy.min_risk_reward
    numerator = entry * (1 + fee) + required * (
        (entry - stop_loss) + fee * (entry + stop_loss)
    )
    return numerator / (1 - fee)


def derive_levels(
    last_price: Decimal,
    bars: Sequence[DailyBar],
    *,
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
    period: int = ATR_PERIOD,
    multiplier: Decimal = ATR_STOP_MULTIPLIER,
) -> LevelPlan:
    """Derive a stop and target for an entry at ``last_price``.

    Args:
        last_price: the validated last traded price the entry is anchored to.
        bars: daily history from a single provider, any order.
        policy: risk limits; supplies the minimum reward-to-risk and fee rate.
        period: ATR lookback.
        multiplier: how many ATR below the entry the stop sits.
    """
    if last_price <= 0:
        return LevelPlan(ok=False, reason=INVALID_ENTRY_PRICE)
    if multiplier <= 0:
        raise ValueError("multiplier must be > 0")

    atr = average_true_range(bars, period)
    if atr is None:
        return LevelPlan(ok=False, reason=INSUFFICIENT_HISTORY)
    if atr <= 0:
        # A flat series gives no volatility to place a stop against.
        return LevelPlan(ok=False, reason=ATR_NOT_POSITIVE, atr=atr)

    stop_loss = (last_price - multiplier * atr).quantize(
        PRICE_QUANTUM, rounding=ROUND_FLOOR
    )
    if stop_loss <= 0:
        # Volatility exceeds the price itself; there is no survivable stop.
        return LevelPlan(ok=False, reason=STOP_NOT_POSITIVE, atr=atr)
    if stop_loss >= last_price:  # pragma: no cover - flooring cannot reach here
        return LevelPlan(ok=False, reason=STOP_NOT_BELOW_ENTRY, atr=atr)

    raw_target = minimum_net_target(last_price, stop_loss, policy)
    if raw_target is None:
        return LevelPlan(ok=False, reason=FEE_RATE_UNUSABLE, atr=atr)

    target = raw_target.quantize(PRICE_QUANTUM, rounding=ROUND_CEILING)

    return LevelPlan(
        ok=True,
        reason=LEVELS_OK,
        stop_loss=stop_loss,
        target=target,
        atr=atr,
        risk_per_share=last_price - stop_loss,
    )


__all__ = [
    "ATR_NOT_POSITIVE",
    "ATR_PERIOD",
    "ATR_STOP_MULTIPLIER",
    "FEE_RATE_UNUSABLE",
    "INSUFFICIENT_HISTORY",
    "INVALID_ENTRY_PRICE",
    "LEVELS_OK",
    "PRICE_QUANTUM",
    "STOP_NOT_BELOW_ENTRY",
    "STOP_NOT_POSITIVE",
    "LevelPlan",
    "average_true_range",
    "derive_levels",
    "minimum_net_target",
]
