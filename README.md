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
- `data-engine/` deterministic Python models, validation, risk sizing, liquidity gate, and provider interface
- `data-engine/src/egx_engine/config.py` the single source of truth for risk and data constants
- `data-engine/src/egx_engine/db/` transactional persistence and the migration runner
- `data-engine/src/egx_engine/pipeline.py` the audited validate -> size -> persist flow
- `db/migrations/` ordered, checksummed PostgreSQL migrations
- `config/` risk policy and Telda universe rules
- `docs/` data-source and build specifications
- `prompts/` Claude decision prompts
- `telegram/` user-facing message templates

## Current state
This repository is the single source of truth for EGX Sentinel. It carries no runtime
dependency on any other project.

Phase 0 (trustworthy deterministic foundation) is complete: packaging and CI, one
central source for every risk constant, a hardened non-mutating validator, and a risk
engine that only accepts validated snapshots.

Phase 1 (persistence) is complete: migrations, a transactional repository, and a
decision pipeline where every decision is traceable from source data through its
validation verdict to the risk calculation that produced it. A decision is returned as
actionable only after it has been committed.

No market-data provider, HTTP service, n8n workflow, or Telegram integration exists yet.

## Market-data policy
No provider is treated as production truth until API access, coverage, timestamp semantics, rate limits, symbol mapping, and redistribution rights are verified. The provider adapter must remain replaceable.

## Running the engine locally
```bash
cd data-engine
pip install -r requirements-dev.txt   # runtime deps live in requirements.txt
pytest
```

Risk constants are stored as decimal fractions (`0.015` == 1.5%). Percentages are a
display format only — see `data-engine/src/egx_engine/config.py`.

## Database
```bash
docker compose up -d postgres
export DATABASE_URL=postgresql://egx:...@127.0.0.1:5433/egx_sentinel
python -m egx_engine.db.migrate
```

Migrations in `db/migrations/` are forward-only, run in numeric order, and each runs in
its own transaction. Every applied migration's checksum is recorded: editing one that
has already run is an error, not a silent divergence. Never modify a database by hand.

The database tests need a **throwaway** database and are skipped without one:
```bash
EGX_TEST_DATABASE_URL=postgresql://egx:...@127.0.0.1:5433/egx_sentinel_test pytest
```

## Safety
This is decision-support software, not financial advice or a profit guarantee. The system must prefer `NO_TRADE` over an unsupported or low-quality trade.
