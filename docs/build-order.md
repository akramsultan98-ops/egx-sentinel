# V1 Build Order

1. Finalize one authorized market-data provider and its timestamp/session semantics.
2. Implement the provider behind the stable Python interface: `health()`, `instruments()`, `snapshot(symbols)`, `daily_bars(symbol, start, end)`.
3. Validate and reject stale/contradictory records before analytics.
4. Compute deterministic indicators and risk metrics in Python.
5. Filter the full EGX universe to a small candidate set using liquidity, trend, momentum, and risk/reward gates.
6. Send validated facts only to the Claude decision layer.
7. Persist signals, user-reported executions, positions, and cash in PostgreSQL.
8. Use n8n for schedules, provider calls, retries, Telegram delivery, and user commands. Do not put core financial calculations inside n8n expressions.
9. Deploy to Hetzner after local validation; keep PostgreSQL private and secrets outside Git.
10. Require a reproducible historical backtest and data-quality checks before real-money recommendations.
