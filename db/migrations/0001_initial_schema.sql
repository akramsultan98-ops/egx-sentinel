CREATE TABLE IF NOT EXISTS instruments (
  instrument_id TEXT PRIMARY KEY,
  ticker TEXT NOT NULL UNIQUE,
  isin TEXT,
  name TEXT NOT NULL,
  exchange TEXT NOT NULL DEFAULT 'EGX',
  sector TEXT,
  asset_type TEXT NOT NULL DEFAULT 'EQUITY',
  currency CHAR(3) NOT NULL DEFAULT 'EGP',
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  source TEXT NOT NULL,
  source_updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS market_snapshots (
  snapshot_id BIGSERIAL PRIMARY KEY,
  instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
  timestamp_utc TIMESTAMPTZ NOT NULL,
  market_timezone TEXT NOT NULL DEFAULT 'Africa/Cairo',
  session_date DATE NOT NULL,
  market_phase TEXT,
  last_price NUMERIC(20,6) NOT NULL CHECK (last_price > 0),
  bid NUMERIC(20,6),
  ask NUMERIC(20,6),
  open NUMERIC(20,6),
  high NUMERIC(20,6),
  low NUMERIC(20,6),
  previous_close NUMERIC(20,6),
  volume BIGINT,
  traded_value_egp NUMERIC(24,4),
  bid_depth NUMERIC(24,4),
  ask_depth NUMERIC(24,4),
  source TEXT NOT NULL,
  source_timestamp TIMESTAMPTZ NOT NULL,
  freshness_seconds INTEGER NOT NULL CHECK (freshness_seconds >= 0),
  validation_status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_instrument_time
  ON market_snapshots (instrument_id, timestamp_utc DESC);

CREATE TABLE IF NOT EXISTS daily_bars (
  instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
  session_date DATE NOT NULL,
  open NUMERIC(20,6) NOT NULL,
  high NUMERIC(20,6) NOT NULL,
  low NUMERIC(20,6) NOT NULL,
  close NUMERIC(20,6) NOT NULL,
  adjusted_close NUMERIC(20,6),
  volume BIGINT NOT NULL DEFAULT 0,
  traded_value_egp NUMERIC(24,4),
  corporate_action_adjusted BOOLEAN NOT NULL DEFAULT FALSE,
  source TEXT NOT NULL,
  PRIMARY KEY (instrument_id, session_date)
);

CREATE TABLE IF NOT EXISTS fundamentals (
  id BIGSERIAL PRIMARY KEY,
  instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
  period_end DATE,
  fiscal_period TEXT,
  source TEXT NOT NULL,
  revenue NUMERIC(24,6),
  net_income NUMERIC(24,6),
  eps NUMERIC(18,6),
  book_value_per_share NUMERIC(18,6),
  total_assets NUMERIC(24,6),
  total_debt NUMERIC(24,6),
  cash NUMERIC(24,6),
  operating_cash_flow NUMERIC(24,6),
  free_cash_flow NUMERIC(24,6),
  roe NUMERIC(18,6),
  roa NUMERIC(18,6),
  pe NUMERIC(18,6),
  pb NUMERIC(18,6),
  dividend_yield NUMERIC(18,6),
  published_at TIMESTAMPTZ,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS news_events (
  event_id BIGSERIAL PRIMARY KEY,
  published_at TIMESTAMPTZ,
  source TEXT NOT NULL,
  headline TEXT NOT NULL,
  url TEXT,
  instrument_id TEXT REFERENCES instruments(instrument_id),
  sector TEXT,
  event_type TEXT,
  materiality TEXT,
  sentiment NUMERIC(8,4),
  summary TEXT,
  raw_reference JSONB,
  UNIQUE(source, url)
);

CREATE INDEX IF NOT EXISTS idx_news_events_published
  ON news_events(published_at DESC);

CREATE TABLE IF NOT EXISTS signals (
  signal_id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
  action TEXT NOT NULL,
  entry_low NUMERIC(20,6),
  entry_high NUMERIC(20,6),
  stop_loss NUMERIC(20,6),
  target_1 NUMERIC(20,6),
  target_2 NUMERIC(20,6),
  target_3 NUMERIC(20,6),
  position_egp NUMERIC(24,4),
  shares BIGINT,
  risk_egp NUMERIC(24,4),
  reward_egp NUMERIC(24,4),
  risk_reward NUMERIC(12,4),
  confidence NUMERIC(5,2),
  market_regime TEXT,
  thesis TEXT,
  invalidation TEXT,
  data_snapshot_id BIGINT REFERENCES market_snapshots(snapshot_id),
  model TEXT,
  status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at DESC);

CREATE TABLE IF NOT EXISTS portfolio (
  portfolio_id BIGSERIAL PRIMARY KEY,
  base_currency CHAR(3) NOT NULL DEFAULT 'EGP',
  initial_capital_egp NUMERIC(24,4) NOT NULL,
  cash_egp NUMERIC(24,4) NOT NULL,
  invested_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  market_value_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  total_equity_egp NUMERIC(24,4) NOT NULL,
  realized_pnl_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  unrealized_pnl_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  drawdown_pct NUMERIC(8,4) NOT NULL DEFAULT 0,
  risk_budget_pct NUMERIC(8,4) NOT NULL DEFAULT 1.5,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS portfolio_positions (
  position_id BIGSERIAL PRIMARY KEY,
  instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
  shares BIGINT NOT NULL CHECK (shares > 0),
  average_entry NUMERIC(20,6) NOT NULL,
  current_price NUMERIC(20,6),
  invested_egp NUMERIC(24,4) NOT NULL,
  market_value_egp NUMERIC(24,4),
  realized_pnl_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  unrealized_pnl_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  stop_loss NUMERIC(20,6),
  target_1 NUMERIC(20,6),
  target_2 NUMERIC(20,6),
  target_3 NUMERIC(20,6),
  thesis TEXT,
  opened_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'OPEN'
);

CREATE TABLE IF NOT EXISTS executions (
  execution_id BIGSERIAL PRIMARY KEY,
  instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
  side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
  shares BIGINT NOT NULL CHECK (shares > 0),
  execution_price NUMERIC(20,6) NOT NULL,
  execution_time TIMESTAMPTZ NOT NULL,
  fees_egp NUMERIC(24,4) NOT NULL DEFAULT 0,
  source TEXT NOT NULL CHECK (source IN ('user_reported', 'broker_statement')),
  telegram_message_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_executions_instrument_time
  ON executions (instrument_id, execution_time DESC);
