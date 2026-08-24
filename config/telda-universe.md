# Telda-First Investment Universe

Only instruments that are actually available for purchase through the user's Telda Invest account may receive a BUY/SELL recommendation.

EGX-listed alone is not sufficient.

## V1 approach
Maintain a manually verified universe from the instruments visible in the Telda
Invest app. It lives in `config/telda-universe.csv` with one row per instrument:

```text
instrument_id,ticker,name,asset_type,sector,telda_available,telda_verified_on
```

Only `telda_available = true` instruments enter the ranking pipeline.

### The file ships with nothing enabled
Every row in the committed CSV carries `telda_available=false` and no
verification date. The repository lists EGX-listed tickers as *candidates for
verification*; it does not — and must not — assert that any of them is
purchasable through Telda. Only the operator can establish that, by opening the
app and looking.

To enable an instrument, set `telda_available=true` **and** fill in
`telda_verified_on` with the date you checked. The two travel together and are
enforced in three places:

1. `load_universe_csv` rejects a file that claims availability without a date.
2. `Repository.load_universe` refuses to store such a claim.
3. A database CHECK constraint (`instruments_telda_available_requires_verification`)
   makes the row unrepresentable.

Loading the file is how the universe reaches the database:

```bash
python -m egx_engine.cli load-universe --file config/telda-universe.csv
```

Rows that are present but disabled are still useful: they register the
instrument, which is what lets a `NOT_IN_TELDA_UNIVERSE` refusal be recorded
with a full audit trail rather than failing as an unknown symbol.

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
