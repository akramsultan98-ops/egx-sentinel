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
- the instrument is not in the validated Telda universe
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
