from datetime import datetime, timezone
from decimal import Decimal

from egx_engine.models import MarketSnapshot
from egx_engine.validator import validate_snapshot


def snapshot(**overrides):
    base = dict(
        instrument_id="TEST",
        ticker="TEST",
        timestamp_utc=datetime.now(timezone.utc),
        session_date=datetime.now(timezone.utc).date(),
        last_price=Decimal("10"),
        open=Decimal("9.5"),
        high=Decimal("10.5"),
        low=Decimal("9.5"),
        source="fixture",
        source_timestamp=datetime.now(timezone.utc),
        freshness_seconds=10,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def test_valid_snapshot_passes():
    result = validate_snapshot(snapshot())
    assert result.valid is True
    assert result.reasons == []


def test_stale_snapshot_is_rejected():
    result = validate_snapshot(snapshot(freshness_seconds=121))
    assert result.valid is False
    assert "STALE_DATA" in result.reasons


def test_crossed_book_is_rejected():
    result = validate_snapshot(snapshot(bid=Decimal("10.2"), ask=Decimal("10.1")))
    assert result.valid is False
    assert "CROSSED_BID_ASK" in result.reasons
