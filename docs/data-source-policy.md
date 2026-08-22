# EGX Data Source Policy — V1

## Primary reference
The Egyptian Exchange (EGX) official platform is the authority for exchange disclosures, listed instruments, corporate announcements, and official market context.

## Live market data
V1 must use an authorized market-data feed/API for live or near-real-time prices. Do not scrape Telda or rely on screenshots as a live feed.

Potential providers are adapters, not hard-coded truth. Before production use, verify API access rights, coverage, timestamp semantics, rate limits, redistribution rights, and symbol mapping.

Candidate research sources:
- EGX official platform
- EGX.news data services
- ICE Egyptian Exchange data

## Validation requirements
Every market snapshot must carry:
- source
- source_timestamp
- freshness_seconds
- validation_status
- market_timezone=Africa/Cairo

A snapshot is not eligible for trading decisions when:
- timestamp is missing
- freshness exceeds the configured threshold
- bid/ask/last are contradictory
- the symbol cannot be mapped to the validated Telda universe
- provider health check fails

## Historical data
Historical daily bars are required for backtesting. Corporate actions must be represented explicitly and adjusted series must not be mixed with raw series without a flag.

## News and disclosures
Use EGX disclosures and reputable news sources. News is a catalyst/context input, not a substitute for price/volume data.

## Principle
No source is allowed to silently become the system's source of truth. The database stores provenance with every material data point.
