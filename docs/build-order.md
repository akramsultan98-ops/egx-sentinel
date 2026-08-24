# V1 Build Order

1. Finalize one authorized market-data provider and its timestamp/session semantics. **(open — the interim `manual` provider stands in)**
2. Implement the provider behind the stable Python interface: `health()`, `instruments()`, `snapshot(symbols)`, `daily_bars(symbol, start, end)`. **(done for `manual`; the registry accepts a licensed adapter unchanged)**
3. Validate and reject stale/contradictory records before analytics. **(done)**
4. Compute deterministic indicators and risk metrics in Python. **(done: ATR stop/target derivation and fee-aware sizing)**
5. Filter the full EGX universe to a small candidate set using liquidity, trend, momentum, and risk/reward gates. **(partial — Telda availability, liquidity, and risk/reward gate; trend and momentum do not)**
6. Send validated facts only to the Claude decision layer. **(not started)**
7. Persist signals, user-reported executions, positions, and cash in PostgreSQL. **(done except `signals`, which the Claude layer will write)**
8. Use n8n for schedules, provider calls, retries, Telegram delivery, and user commands. Do not put core financial calculations inside n8n expressions. **(not started; the CLI is the callable surface today)**
9. Deploy to Hetzner after local validation; keep PostgreSQL private and secrets outside Git. **(not started)**
10. Require a reproducible historical backtest and data-quality checks before real-money recommendations. **(not started — bars are now stored, which is the prerequisite)**

## Still blocking real money
- No licensed market-data provider (step 1).
- The fee schedule is an unverified conservative placeholder.
- No backtest (step 10).
- No market-session calendar, so a scheduled scan cannot yet tell a closed market from an open one.
