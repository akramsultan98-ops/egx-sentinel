-- Phase 2: make the Telda investment universe enforceable data.
--
-- config/telda-universe.md states the rule the system has never been able to
-- apply: EGX-listed is not sufficient, only instruments actually purchasable
-- through the operator's Telda Invest account may receive a BUY. Until now
-- that gate existed in prose only. These two columns turn it into state the
-- engine can check, and the CHECK constraint below makes it impossible to
-- assert availability without recording when a human verified it.

ALTER TABLE instruments
  ADD COLUMN IF NOT EXISTS telda_available BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS telda_verified_at TIMESTAMPTZ;

-- Availability is a claim about the outside world, so it may only be recorded
-- alongside the date a human checked it. Unverified means unavailable: the
-- default above is FALSE, and nothing can flip it without a verification
-- timestamp.
ALTER TABLE instruments
  ADD CONSTRAINT instruments_telda_available_requires_verification
  CHECK (telda_available = FALSE OR telda_verified_at IS NOT NULL);

-- The scan reads the tradeable universe on every run.
CREATE INDEX IF NOT EXISTS idx_instruments_telda_available
  ON instruments (telda_available)
  WHERE telda_available = TRUE;
