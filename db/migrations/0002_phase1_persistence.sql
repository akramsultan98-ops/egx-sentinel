-- Phase 1: reconcile the schema with the canonical Phase 0 Python models and
-- make the system auditable end to end.
--
-- The Phase 0 models are authoritative. Nothing here changes decision logic;
-- it gives every step of a decision a place to be recorded and constrains the
-- database to the same vocabulary the engine already enforces in code.

-- ---------------------------------------------------------------------------
-- Enum constraints matching the Phase 0 literals
-- ---------------------------------------------------------------------------

-- egx_engine.models.ValidationStatus
ALTER TABLE market_snapshots
  ADD CONSTRAINT market_snapshots_validation_status_check
  CHECK (validation_status IN ('VALID', 'STALE', 'INVALID', 'UNVERIFIED'));

ALTER TABLE portfolio_positions
  ADD CONSTRAINT portfolio_positions_status_check
  CHECK (status IN ('OPEN', 'CLOSED'));

-- ---------------------------------------------------------------------------
-- Idempotency: n8n retries must not duplicate market history
-- ---------------------------------------------------------------------------

-- One snapshot per (instrument, source, source timestamp). Re-delivering the
-- same tick is a no-op rather than a second row.
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_snapshots_provenance
  ON market_snapshots (instrument_id, source, source_timestamp);

-- daily_bars previously keyed on (instrument_id, session_date) with `source`
-- outside the key, so two providers silently overwrote one another.
ALTER TABLE daily_bars DROP CONSTRAINT daily_bars_pkey;
ALTER TABLE daily_bars ADD PRIMARY KEY (instrument_id, session_date, source);

-- ---------------------------------------------------------------------------
-- Portfolio identity and derived-value removal
-- ---------------------------------------------------------------------------

-- A portfolio needs a stable handle: "current equity" is an input to position
-- sizing and must never be ambiguous.
ALTER TABLE portfolio ADD COLUMN IF NOT EXISTS name TEXT;
UPDATE portfolio SET name = 'portfolio-' || portfolio_id WHERE name IS NULL;
ALTER TABLE portfolio ALTER COLUMN name SET NOT NULL;
ALTER TABLE portfolio ADD CONSTRAINT uq_portfolio_name UNIQUE (name);

ALTER TABLE portfolio ADD CONSTRAINT portfolio_cash_non_negative CHECK (cash_egp >= 0);

-- These are all recomputable from positions plus validated prices. Storing them
-- created a second source of truth for equity; the portfolio_state view below
-- replaces them. cash_egp and realized_pnl_egp stay: they are ledger facts
-- maintained transactionally alongside each execution, not derived snapshots.
ALTER TABLE portfolio
  DROP COLUMN invested_egp,
  DROP COLUMN market_value_egp,
  DROP COLUMN total_equity_egp,
  DROP COLUMN unrealized_pnl_egp,
  DROP COLUMN drawdown_pct;

-- ---------------------------------------------------------------------------
-- Positions belong to a portfolio
-- ---------------------------------------------------------------------------

ALTER TABLE portfolio_positions
  ADD COLUMN IF NOT EXISTS portfolio_id BIGINT REFERENCES portfolio(portfolio_id);

-- Attach any pre-existing rows to the single existing portfolio. If that is
-- ambiguous the NOT NULL below fails loudly rather than guessing.
UPDATE portfolio_positions
   SET portfolio_id = (SELECT portfolio_id FROM portfolio ORDER BY portfolio_id LIMIT 1)
 WHERE portfolio_id IS NULL;
ALTER TABLE portfolio_positions ALTER COLUMN portfolio_id SET NOT NULL;

ALTER TABLE portfolio_positions
  DROP COLUMN current_price,
  DROP COLUMN market_value_egp,
  DROP COLUMN unrealized_pnl_egp,
  DROP COLUMN invested_egp;

ALTER TABLE portfolio_positions
  ADD CONSTRAINT portfolio_positions_average_entry_positive CHECK (average_entry > 0);

-- A fully sold position must remain on record with zero shares; deleting it
-- would destroy the audit trail. The original CHECK (shares > 0) made that
-- impossible.
ALTER TABLE portfolio_positions DROP CONSTRAINT portfolio_positions_shares_check;
ALTER TABLE portfolio_positions
  ADD CONSTRAINT portfolio_positions_shares_check
  CHECK (shares >= 0 AND (shares > 0 OR status = 'CLOSED'));

ALTER TABLE portfolio_positions ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;

-- At most one open position per instrument per portfolio.
CREATE UNIQUE INDEX IF NOT EXISTS uq_open_position_per_instrument
  ON portfolio_positions (portfolio_id, instrument_id)
  WHERE status = 'OPEN';

-- ---------------------------------------------------------------------------
-- Executions: ownership and duplicate protection
-- ---------------------------------------------------------------------------

ALTER TABLE executions
  ADD COLUMN IF NOT EXISTS portfolio_id BIGINT REFERENCES portfolio(portfolio_id);
UPDATE executions
   SET portfolio_id = (SELECT portfolio_id FROM portfolio ORDER BY portfolio_id LIMIT 1)
 WHERE portfolio_id IS NULL;
ALTER TABLE executions ALTER COLUMN portfolio_id SET NOT NULL;

-- Caller-supplied key (e.g. a Telegram message id in a later phase). Re-sending
-- the same execution report must never move the portfolio twice.
ALTER TABLE executions ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
UPDATE executions SET idempotency_key = 'legacy-' || execution_id WHERE idempotency_key IS NULL;
ALTER TABLE executions ALTER COLUMN idempotency_key SET NOT NULL;
ALTER TABLE executions ADD CONSTRAINT uq_executions_idempotency UNIQUE (idempotency_key);

ALTER TABLE executions
  ADD CONSTRAINT executions_price_positive CHECK (execution_price > 0),
  ADD CONSTRAINT executions_fees_non_negative CHECK (fees_egp >= 0);

ALTER TABLE executions ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- ---------------------------------------------------------------------------
-- Audit chain: validation results
-- ---------------------------------------------------------------------------

-- Mirrors egx_engine.validator.ValidationResult. Multiple rows per snapshot are
-- allowed: re-validating under a different policy is a new audit record, never
-- an overwrite of the old verdict.
CREATE TABLE validation_results (
  validation_result_id BIGSERIAL PRIMARY KEY,
  snapshot_id BIGINT NOT NULL REFERENCES market_snapshots(snapshot_id) ON DELETE RESTRICT,
  status TEXT NOT NULL CHECK (status IN ('VALID', 'STALE', 'INVALID', 'UNVERIFIED')),
  reasons TEXT[] NOT NULL DEFAULT '{}',
  max_freshness_seconds INTEGER NOT NULL CHECK (max_freshness_seconds >= 0),
  data_policy JSONB NOT NULL,
  validated_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- A VALID verdict cannot carry findings, and a non-VALID one cannot be empty.
  CONSTRAINT validation_results_reasons_match_status CHECK (
    (status = 'VALID' AND cardinality(reasons) = 0)
    OR (status <> 'VALID' AND cardinality(reasons) > 0)
  )
);

CREATE INDEX idx_validation_results_snapshot
  ON validation_results (snapshot_id, validated_at DESC);

-- ---------------------------------------------------------------------------
-- Audit chain: deterministic risk plans
-- ---------------------------------------------------------------------------

-- Mirrors egx_engine.models.RiskPlan. These values are derived, but they are
-- persisted deliberately: they are the record of what the engine decided, with
-- which inputs, under which policy. Recomputing them later would use today's
-- policy and today's prices, which is not what was decided.
CREATE TABLE risk_plans (
  risk_plan_id BIGSERIAL PRIMARY KEY,
  validation_result_id BIGINT NOT NULL
    REFERENCES validation_results(validation_result_id) ON DELETE RESTRICT,
  instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
  portfolio_id BIGINT NOT NULL REFERENCES portfolio(portfolio_id),

  action TEXT NOT NULL CHECK (action IN ('BUY', 'NO_TRADE')),
  reason TEXT NOT NULL,

  entry NUMERIC(20,6) CHECK (entry IS NULL OR entry > 0),
  stop_loss NUMERIC(20,6) CHECK (stop_loss IS NULL OR stop_loss > 0),
  target NUMERIC(20,6) CHECK (target IS NULL OR target > 0),
  shares BIGINT NOT NULL DEFAULT 0 CHECK (shares >= 0),

  position_value_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  concentration_fraction NUMERIC(12,8) NOT NULL DEFAULT 0,
  fees_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  risk_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  reward_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  risk_reward NUMERIC(16,8) NOT NULL DEFAULT 0,
  risk_reward_gross NUMERIC(16,8) NOT NULL DEFAULT 0,

  -- Portfolio inputs as they stood at decision time. Equity moves; the audit
  -- record must show what the sizing actually used.
  equity_egp_at_decision NUMERIC(24,4) NOT NULL CHECK (equity_egp_at_decision > 0),
  cash_egp_at_decision NUMERIC(24,4) NOT NULL CHECK (cash_egp_at_decision >= 0),
  open_positions_at_decision INTEGER NOT NULL CHECK (open_positions_at_decision >= 0),

  risk_policy JSONB NOT NULL,
  liquidity_gate TEXT NOT NULL,
  engine_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- A BUY must be fully specified; nothing else may claim shares.
  CONSTRAINT risk_plans_buy_is_complete CHECK (
    action <> 'BUY'
    OR (entry IS NOT NULL AND stop_loss IS NOT NULL AND target IS NOT NULL AND shares > 0)
  ),
  CONSTRAINT risk_plans_no_trade_has_no_shares CHECK (action = 'BUY' OR shares = 0)
);

CREATE INDEX idx_risk_plans_created ON risk_plans (created_at DESC);
CREATE INDEX idx_risk_plans_instrument ON risk_plans (instrument_id, created_at DESC);
CREATE INDEX idx_risk_plans_portfolio ON risk_plans (portfolio_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Link the Claude decision record to the deterministic record it must respect
-- ---------------------------------------------------------------------------

ALTER TABLE signals
  ADD COLUMN IF NOT EXISTS risk_plan_id BIGINT REFERENCES risk_plans(risk_plan_id),
  ADD COLUMN IF NOT EXISTS portfolio_id BIGINT REFERENCES portfolio(portfolio_id);

-- ---------------------------------------------------------------------------
-- portfolio_state: the single computed source for equity
-- ---------------------------------------------------------------------------

-- Equity is cash plus the market value of open positions, priced only from
-- snapshots that actually validated. If any open position has no validated
-- price, market value and equity resolve to NULL: unknown equity must fail
-- closed rather than be guessed from cost basis.
CREATE VIEW portfolio_state AS
WITH latest_valid_price AS (
  SELECT DISTINCT ON (instrument_id)
         instrument_id,
         last_price,
         timestamp_utc AS priced_at
    FROM market_snapshots
   WHERE validation_status = 'VALID'
   ORDER BY instrument_id, timestamp_utc DESC
),
open_positions AS (
  SELECT p.portfolio_id,
         COUNT(*) AS open_positions,
         SUM(p.shares * p.average_entry) AS invested_egp,
         SUM(p.shares * lvp.last_price) AS market_value_egp,
         COUNT(*) FILTER (WHERE lvp.last_price IS NULL) AS unpriced_positions
    FROM portfolio_positions p
    LEFT JOIN latest_valid_price lvp ON lvp.instrument_id = p.instrument_id
   WHERE p.status = 'OPEN'
   GROUP BY p.portfolio_id
)
SELECT pf.portfolio_id,
       pf.name,
       pf.base_currency,
       pf.initial_capital_egp,
       pf.cash_egp,
       pf.realized_pnl_egp,
       pf.risk_budget_pct,
       COALESCE(op.open_positions, 0) AS open_positions,
       COALESCE(op.invested_egp, 0) AS invested_egp,
       CASE WHEN COALESCE(op.unpriced_positions, 0) > 0
            THEN NULL
            ELSE COALESCE(op.market_value_egp, 0)
       END AS market_value_egp,
       CASE WHEN COALESCE(op.unpriced_positions, 0) > 0
            THEN NULL
            ELSE pf.cash_egp + COALESCE(op.market_value_egp, 0)
       END AS total_equity_egp,
       CASE WHEN COALESCE(op.unpriced_positions, 0) > 0
            THEN NULL
            ELSE COALESCE(op.market_value_egp, 0) - COALESCE(op.invested_egp, 0)
       END AS unrealized_pnl_egp,
       COALESCE(op.unpriced_positions, 0) AS unpriced_positions,
       pf.updated_at
  FROM portfolio pf
  LEFT JOIN open_positions op ON op.portfolio_id = pf.portfolio_id;
