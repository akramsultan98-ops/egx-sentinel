# EGX Sentinel

Personal AI decision-support system for an initial EGP 5,000 Egyptian Exchange (EGX) portfolio, executed manually through Telda.

## Mission
Provide evidence-grounded, risk-controlled market decisions and portfolio tracking through Telegram, orchestrated by n8n.

## V1 principles
- Human-in-the-loop only. No automatic order execution.
- Telda availability is a hard execution gate.
- Market data must be verified and fresh before any trade decision.
- Python owns deterministic validation, calculations, and position sizing.
- Claude reasons over validated facts; it is never the source of truth for prices, balances, fills, or calculations.
- PostgreSQL stores portfolio state, market provenance, signals, and executions.
- `DATA_NOT_VERIFIED_NO_TRADE` is a hard safety outcome.
- Cash is always a valid position.

## Architecture
Market Data → n8n → Python Validation/Risk Engine → Claude Decision Layer → PostgreSQL → Telegram → Manual Telda Execution

## Repository layout
- `data-engine/` deterministic Python models, validation, risk sizing, and provider interface
- `db/` canonical PostgreSQL schema
- `config/` risk policy and Telda universe rules
- `docs/` data-source and build specifications
- `prompts/` Claude decision prompts
- `telegram/` user-facing message templates

## Current state
This repository is the clean EGX-only extraction of the useful work previously developed inside `akram-ai-system`. Unrelated Digital Products / Akram AI System material is intentionally excluded.

## Market-data policy
No provider is treated as production truth until API access, coverage, timestamp semantics, rate limits, symbol mapping, and redistribution rights are verified. The provider adapter must remain replaceable.

## Safety
This is decision-support software, not financial advice or a profit guarantee. The system must prefer `NO_TRADE` over an unsupported or low-quality trade.
