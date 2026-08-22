# n8n Architecture — V1

n8n is the orchestration layer, not the financial calculation engine.

## Planned workflows

### 1. Daily / scheduled market scan
Schedule → fetch market data → normalize → Python validation/risk gate → shortlist → Claude decision → PostgreSQL → Telegram.

### 2. On-demand `/scan`
Telegram Trigger → command validation → fresh data fetch → validation/risk → Claude → PostgreSQL → Telegram response.

### 3. Portfolio status
Telegram Trigger → PostgreSQL portfolio state → latest verified prices → deterministic P/L calculation → Telegram.

### 4. Execution capture
Telegram Trigger → parse `BOUGHT TICKER PRICE SHARES` or `SOLD TICKER PRICE SHARES` → validate against known instrument → PostgreSQL transaction → acknowledge.

### 5. Position monitoring
Schedule → fetch fresh prices → validate → compare against stop/targets/invalidation → Telegram only when state materially changes.

## Existing n8n credentials to reuse
The existing n8n instance already has Anthropic, PostgreSQL, and Telegram credentials. Do not create duplicate credentials when the existing credentials are appropriate.

## Hard boundary
Do not calculate position sizing, risk/reward, P/L, or other core financial math in n8n expressions. Call the Python engine or a deterministic service instead.
