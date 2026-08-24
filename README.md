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
- `data-engine/src/egx_engine/settings.py` everything that comes from the environment
- `data-engine/src/egx_engine/levels.py` deterministic ATR stop/target derivation
- `data-engine/src/egx_engine/universe.py` the Telda availability gate
- `data-engine/src/egx_engine/providers.py` provider registry and the manual file provider
- `data-engine/src/egx_engine/db/` transactional persistence and the migration runner
- `data-engine/src/egx_engine/pipeline.py` the audited validate -> size -> persist flow
- `data-engine/src/egx_engine/cli.py` the operator command line
- `db/migrations/` ordered, checksummed PostgreSQL migrations
- `config/` risk policy, and the operator-verified Telda universe (`.csv` + rules)
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

Phase 2 (end-to-end analysis) is complete: the Telda universe is a database-backed
hard gate, daily bars are stored, stops and targets are derived deterministically
from volatility, and one CLI runs the whole flow. The interim provider reads
operator-maintained files and receives no exemptions from validation.

No licensed market-data provider, Claude decision layer, HTTP service, n8n workflow,
or Telegram integration exists yet. The system analyses and records; it never executes.

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

## Running a scan
The engine is analysis-only. Nothing here places an order.

```bash
export DATABASE_URL=postgresql://egx:...@127.0.0.1:5433/egx_sentinel
export MARKET_DATA_PROVIDER=manual
export MARKET_DATA_DIR=/path/to/market-data
export EGX_PORTFOLIO_ID=1

python -m egx_engine.cli load-universe          # register the verified universe
python -m egx_engine.cli ingest                 # store daily bars
python -m egx_engine.cli scan                   # decide, persist, print JSON
```

`MARKET_DATA_DIR` holds `snapshots.json` (a JSON array of quotes) and
`bars/<TICKER>.csv`. Nothing in the committed universe file is tradeable until
an operator verifies it in the Telda app — see `config/telda-universe.md`.

Until a licensed feed is authorised, `MARKET_DATA_PROVIDER=manual` is the only
provider that returns data, and it is validated exactly like a vendor feed
would be. `unconfigured` (the default) refuses outright.

## The MVP: n8n → Sentinel → Telegram

n8n orchestrates; Sentinel decides. One endpoint connects them.

```bash
docker compose up -d postgres
docker compose run --rm sentinel python -m egx_engine.db.migrate
docker compose up -d sentinel
```

`POST /decide` takes machine-supplied quotes plus AI research and returns the
decision. The same request works through the CLI:

```bash
python -m egx_engine.cli decide < request.json
```

### The rule that makes this safe
**Machines supply numbers. The AI supplies words.**

`entry`, `stop_loss`, `target`, `shares`, `risk_egp` and the BUY/NO_TRADE
verdict are computed by the engine from validated market data. The research
object is untrusted input: it is scanned for price- and size-shaped fields and
the request is *rejected* if any are found, and it is only read after the
decision already exists. It reaches `signals.thesis`, `signals.confidence` and
`signals.model`, and nothing else. There is no code path by which a model can
move a stop or size a position.

This matters because the validator checks internal consistency and freshness,
not truth. A hallucinated price carrying a plausible timestamp would pass every
gate in the system. So a language model is never allowed to supply one.

If the AI says BUY and the engine says NO_TRADE, the answer is NO_TRADE.

### Model choice lives in n8n
The engine has no AI dependency, no provider SDK, and no model API key. It
never learns which model produced the research it stores. Swapping Claude for
GPT, Gemini, Groq or OpenRouter is an n8n credential change and touches no
Python.

### Test data is labelled
Quotes carry their own `source` (`google_sheet`, `manual`, a vendor name),
which is persisted and returned as `snapshot_source`. Any decision built on
`manual`/`test`/`fixture` data comes back with `data_is_test: true` so it can
never be mistaken for a live signal.

### Security
The decision endpoint requires a bearer token and refuses to start without
`SENTINEL_API_TOKEN`. Neither it nor PostgreSQL publishes a host port: both are
reachable only from the private Docker network. Secrets live in n8n credentials
and server environment variables, never in Git.

### Not built, deliberately
No order placement, no broker or Telda integration, no browser automation, no
scheduler inside Python. Sentinel recommends; a human executes.

## Safety
This is decision-support software, not financial advice or a profit guarantee. The system must prefer `NO_TRADE` over an unsupported or low-quality trade.
