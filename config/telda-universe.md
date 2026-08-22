# Telda-First Investment Universe

Only instruments that are actually available for purchase through the user's Telda Invest account may receive a BUY/SELL recommendation.

EGX-listed alone is not sufficient.

## V1 approach
Maintain a manually verified universe from the instruments visible in the Telda Invest app. Store:
- ticker
- company/fund name
- asset type
- sector
- Telda available = true/false
- last verified date

Only `Telda available = true` instruments enter the AI ranking pipeline.

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
