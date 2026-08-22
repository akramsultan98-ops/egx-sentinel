# EGX Sentinel — Risk Policy V1

## Portfolio
- Initial capital: EGP 5,000
- Execution app: Telda
- Execution mode: human-in-the-loop only
- Maximum risk per tactical position: 1.5% of current equity
- Initial maximum risk budget: EGP 75
- Maximum simultaneous tactical positions: 2
- Minimum risk/reward for a BUY: 1:2
- Cash is always an allowed position

## Hard gates
A BUY is forbidden when any of the following is true:
- market data is stale, missing, contradictory, or unverified
- the instrument is not in the validated Telda universe
- liquidity is insufficient for the intended position
- risk/reward is below 1:2
- stop-loss cannot be defined from market structure or volatility
- the market is closed and the signal is not explicitly marked as a next-session setup

## Position sizing
```text
max_risk_egp = current_equity_egp * 0.015
shares = floor(max_risk_egp / abs(entry_price - stop_loss))
position_value = shares * entry_price
```

The final position must satisfy both the risk limit and available cash.

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
