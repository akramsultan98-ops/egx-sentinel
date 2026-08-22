from __future__ import annotations

from datetime import datetime, timezone

from .models import MarketSnapshot


class ValidationResult:
    def __init__(self, valid: bool, reasons: list[str]):
        self.valid = valid
        self.reasons = reasons


def validate_snapshot(snapshot: MarketSnapshot, max_freshness_seconds: int = 120) -> ValidationResult:
    reasons: list[str] = []

    if snapshot.freshness_seconds > max_freshness_seconds:
        reasons.append("STALE_DATA")

    if snapshot.last_price <= 0:
        reasons.append("INVALID_LAST_PRICE")

    if snapshot.bid is not None and snapshot.ask is not None and snapshot.bid > snapshot.ask:
        reasons.append("CROSSED_BID_ASK")

    if snapshot.low is not None and snapshot.high is not None:
        if snapshot.low > snapshot.high:
            reasons.append("INVALID_HIGH_LOW")
        if not (snapshot.low <= snapshot.last_price <= snapshot.high):
            reasons.append("LAST_OUTSIDE_SESSION_RANGE")

    if snapshot.open is not None and snapshot.high is not None and snapshot.low is not None:
        if not (snapshot.low <= snapshot.open <= snapshot.high):
            reasons.append("OPEN_OUTSIDE_SESSION_RANGE")

    if snapshot.source_timestamp.tzinfo is None:
        reasons.append("SOURCE_TIMESTAMP_MISSING_TZ")
    else:
        age = (datetime.now(timezone.utc) - snapshot.source_timestamp).total_seconds()
        if age < -30:
            reasons.append("SOURCE_TIMESTAMP_IN_FUTURE")

    snapshot.validation_status = "VALID" if not reasons else "INVALID"
    return ValidationResult(valid=not reasons, reasons=reasons)
