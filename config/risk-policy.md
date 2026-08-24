# EGX Sentinel — Risk Policy V1

## Canonical representation
Every ratio below is implemented in `data-engine/src/egx_engine/config.py` as a
**decimal fraction of 1**, never as a percentage: `0.015` means 1.5%.
Percentages appear only in prose and in percent-typed database columns
(`portfolio.risk_budget_pct` stores `1.5`); they are a display format and must
never be fed back into a calculation. `egx_engine.config.as_percent()` is the
only sanctioned conversion.

That module is the single source of truth. This document describes it; it does
not independently define the numbers.

## Portfolio
- Initial capital: EGP 5,000
- Execution app: Telda
- Execution mode: human-in-the-loop only
- Maximum risk per tactical position: 1.5% of current equity
- Initial maximum risk budget: EGP 75
- Maximum simultaneous tactical positions: 2
- Maximum notional per position: 30% of equity (2 positions leave a 40% cash buffer)
- Maximum entry deviation from the validated last price: 2%
- Minimum risk/reward for a BUY: 1:2, measured **net of estimated fees**
- Cash is always an allowed position

## Hard gates
A BUY is forbidden when any of the following is true:
- market data is stale, missing, contradictory, or unverified
- the instrument is not in the validated Telda universe (enforced in
  `pipeline.py` against `instruments.telda_available`)
- liquidity is insufficient for the intended position
- risk/reward is below 1:2 before or after fees
- the proposed entry is not anchored to the validated last traded price
- the resulting notional would exceed the concentration limit
- the maximum number of open positions is already held
- stop-loss cannot be defined from market structure or volatility
- the market is closed and the signal is not explicitly marked as a next-session setup

## Position sizing
Share count is the smallest of four independent constraints, all fee-aware:

```text
risk_budget_egp        = current_equity_egp * risk_per_trade_fraction   # 0.015
concentration_budget   = current_equity_egp * max_position_concentration_fraction

shares_by_risk          = max n where n*(entry-stop) + fee(entry*n) + fee(stop*n) <= risk_budget_egp
shares_by_cash          = max n where n*entry + fee(entry*n) <= cash_egp
shares_by_concentration = floor(concentration_budget / entry)
shares_by_liquidity     = floor(liquidity_gate.max_position_value_egp / entry)

shares = min(shares_by_risk, shares_by_cash, shares_by_concentration, shares_by_liquidity)
```

Risk is reported inclusive of the round-trip commission paid on entry and on a
stop-out, so `risk_egp` never understates the real loss.

### Fees
The fee schedule is an **unverified placeholder** (`fee_rate_fraction`,
`min_fee_egp`). It is deliberately non-zero because ignoring fees understates
risk; a conservative rate can only shrink a position, never inflate one. It must
be replaced with the verified Telda/broker schedule before real-money use.

### Liquidity
Liquidity is a hard gate with a fail-closed default. Until a verified market-data
provider supplies the inputs, `UnconfiguredLiquidityGate` returns
`LIQUIDITY_NOT_VERIFIED` and no BUY can be produced.

## Stop-loss and target derivation
`data-engine/src/egx_engine/levels.py` derives both levels deterministically
from daily bars, so the system can originate a setup rather than only score one
a human supplied:

```text
atr    = Wilder ATR over 14 completed sessions   # needs 15 bars
stop   = last_price - 2 * atr                    # rounded down to 0.001
target = smallest price whose reward/risk clears min_risk_reward NET of fees
```

If ATR cannot be computed — fewer than 15 bars, or a perfectly flat series —
the result is a refusal (`INSUFFICIENT_HISTORY`, `ATR_NOT_POSITIVE`) that is
persisted as a NO_TRADE. A stop is never guessed.

The target solves for *net* reward-to-risk rather than gross. A target set at
exactly `entry + R x risk` always lands below `R` once fees are taken out, so a
gross formula would make every derived setup fail the gate it was built to
satisfy. The derivation assumes the proportional part of the fee model; if
`min_fee_egp` is raised above zero the real fee can exceed the modelled one and
the risk engine — which re-checks net reward-to-risk itself — will reject the
setup. Levels propose; `risk.py` decides.

## Decision hierarchy
1. Data validity
2. Market regime
3. Liquidity
4. Risk/reward
5. Technical setup
6. Catalyst/news
7. Fundamentals

## Safety principle
The system is an investment decision-support tool, not a profit guarantee. It must prefer `NO_TRADE` over a low-quality trade.
