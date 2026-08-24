# Telda-First Investment Universe

Only instruments that are actually available for purchase through the user's Telda Invest account may receive a BUY/SELL recommendation.

EGX-listed alone is not sufficient.

## V1 approach
Maintain a manually verified universe from the instruments visible in the Telda
Invest app. It ships as package data at
`data-engine/src/egx_engine/data/telda-universe.csv`, with one row per
instrument:

```text
instrument_id,ticker,name,asset_type,sector,telda_available,telda_verified_on
```

Only `telda_available = true` instruments enter the ranking pipeline.

### The file is the operator's verified record
The committed CSV holds the universe the operator confirmed in the Telda Invest
app on **2026-08-25**: 244 instruments enabled, plus any instrument that is
registered but not available.

It began as a candidates-only list with nothing enabled, because nobody had
checked the app yet. It is now a verified record, and that distinction matters:
the repository still does not — and must not — assert Telda availability on its
own. Every enabled row exists because a human opened the app and looked. Re-verify
when Telda changes its offering, and move the date when you do.

To enable an instrument, set `telda_available=true` **and** fill in
`telda_verified_on` with the date you checked. The two travel together and are
enforced in three places:

1. `load_universe_csv` rejects a file that claims availability without a date.
2. `Repository.load_universe` refuses to store such a claim.
3. A database CHECK constraint (`instruments_telda_available_requires_verification`)
   makes the row unrepresentable.

Loading the file is how the universe reaches the database:

```bash
python -m egx_engine.cli load-universe                    # the shipped seed
python -m egx_engine.cli load-universe --file /path/to/your.csv   # your own list
```

In the container the seed travels inside the installed package, so
`load-universe` works with no arguments. To load a list you maintain outside the
image, mount it and pass `--file`.

Rows that are present but disabled are still useful: they register the
instrument, which is what lets a `NOT_IN_TELDA_UNIVERSE` refusal be recorded
with a full audit trail rather than failing as an unknown symbol.

### Symbols carried verbatim
Three entries are transcribed exactly as the operator supplied them and have
**not** been normalised, because correcting a ticker is indistinguishable from
inventing one:

- `IRAX.CA`, `PACH.CA`, `TORA.CA` — carry a `.CA` (Cairo) vendor suffix that the
  other 241 symbols do not.

They cannot match a real feed while written this way, so they are inert rather
than dangerous: a quote will simply never arrive for them. Correct them at the
source and reload.

### Held back pending verification
`ESRS` (Ezz Steel) is registered but **not** available, and carries no
verification date — nothing has been established either way. It was delisted
from EGX in March 2025 and moved to an OTC facility, so its presence in the
Telda list needs an explicit check before it can be enabled. It is deliberately
not deleted: a registered instrument produces a persisted
`NOT_IN_TELDA_UNIVERSE` refusal, which is more auditable than an unknown symbol.

### The gate
`egx_engine.universe.check_universe` runs inside the decision pipeline, before
sizing. An unknown instrument, an unverified one, and an explicitly unavailable
one are all refused. Availability is verified state, not a market fact, so the
check lives in the pipeline rather than in the pure risk engine.

## Data priority
1. Telda-visible universe for execution compatibility
2. EGX / licensed market data for market facts
3. Company filings / official disclosures for fundamentals and catalysts
4. Reputable financial news for context

## Safety rule
If Telda availability or market data cannot be verified: `DATA_NOT_VERIFIED_NO_TRADE`.

## V1 exclusions
- automatic order execution
- securities not verified as available on Telda
- leverage/margin
- derivatives
- unsupported funds/instruments
