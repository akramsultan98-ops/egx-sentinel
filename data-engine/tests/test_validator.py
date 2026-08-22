"""Validator tests: one per failure mode identified in the Phase 0 audit."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from egx_engine.config import DataPolicy
from egx_engine.validator import validate_snapshot

from conftest import NOW, make_snapshot


# --- happy path ---------------------------------------------------------


def test_valid_snapshot_passes(snapshot, now):
    result = validate_snapshot(snapshot, now=now)
    assert result.valid is True
    assert result.status == "VALID"
    assert result.reasons == []
    assert result.snapshot.validation_status == "VALID"


def test_validation_does_not_mutate_the_input(snapshot, now):
    """The caller's object must never be stamped in place."""
    assert snapshot.validation_status == "UNVERIFIED"
    result = validate_snapshot(snapshot, now=now)
    assert snapshot.validation_status == "UNVERIFIED"
    assert result.snapshot is not snapshot
    assert result.snapshot.validation_status == "VALID"


def test_validation_is_deterministic(snapshot, now):
    first = validate_snapshot(snapshot, now=now)
    second = validate_snapshot(snapshot, now=now)
    assert (first.status, first.reasons) == (second.status, second.reasons)


def test_now_must_be_timezone_aware(snapshot):
    with pytest.raises(ValueError):
        validate_snapshot(snapshot, now=datetime(2026, 3, 11, 10, 0, 0))


# --- staleness ----------------------------------------------------------


def test_self_reported_staleness_is_rejected(now):
    result = validate_snapshot(
        make_snapshot(
            freshness_seconds=200,
            source_timestamp=NOW - timedelta(seconds=200),
        ),
        now=now,
    )
    assert result.valid is False
    assert result.status == "STALE"
    assert "STALE_DATA" in result.reasons


def test_stale_is_labelled_stale_not_invalid(now):
    """STALE and INVALID are different outcomes and must not be conflated."""
    result = validate_snapshot(
        make_snapshot(
            freshness_seconds=300,
            source_timestamp=NOW - timedelta(seconds=300),
        ),
        now=now,
    )
    assert result.status == "STALE"
    assert result.snapshot.validation_status == "STALE"


def test_source_timestamp_age_alone_can_make_a_snapshot_stale(now):
    """Honest-but-old data: freshness matches evidence, but exceeds the limit."""
    result = validate_snapshot(
        make_snapshot(
            freshness_seconds=600,
            source_timestamp=NOW - timedelta(seconds=600),
        ),
        now=now,
    )
    assert result.status == "STALE"
    assert "STALE_SOURCE_TIMESTAMP" in result.reasons


# --- dishonest freshness (regression tests) ------------------------------


def test_dishonest_freshness_cannot_become_valid(now):
    """REGRESSION: provider claims 5s while the tick is three hours old.

    Before Phase 0 this returned VALID because freshness_seconds was trusted
    without ever being compared to source_timestamp.
    """
    result = validate_snapshot(
        make_snapshot(
            freshness_seconds=5,
            source_timestamp=NOW - timedelta(hours=3),
        ),
        now=now,
    )
    assert result.valid is False
    assert result.status == "INVALID"
    assert "FRESHNESS_MISREPORTED" in result.reasons
    assert "STALE_SOURCE_TIMESTAMP" in result.reasons
    assert result.snapshot.validation_status == "INVALID"


def test_mildly_dishonest_freshness_is_still_rejected(now):
    """A claim inside the freshness limit but contradicted by the evidence."""
    result = validate_snapshot(
        make_snapshot(
            freshness_seconds=10,
            source_timestamp=NOW - timedelta(seconds=115),
        ),
        now=now,
    )
    assert result.valid is False
    assert "FRESHNESS_MISREPORTED" in result.reasons


def test_freshness_within_tolerance_is_accepted(now):
    """Small disagreement is normal transport latency, not dishonesty."""
    result = validate_snapshot(
        make_snapshot(freshness_seconds=10, source_timestamp=NOW - timedelta(seconds=25)),
        now=now,
    )
    assert result.valid is True


def test_dishonesty_outranks_staleness_in_classification(now):
    """A record that is both old and self-contradictory is INVALID, not STALE."""
    result = validate_snapshot(
        make_snapshot(freshness_seconds=1, source_timestamp=NOW - timedelta(days=1)),
        now=now,
    )
    assert result.status == "INVALID"


# --- timestamps ---------------------------------------------------------


def test_naive_timestamp_utc_is_unverified(now):
    result = validate_snapshot(
        make_snapshot(timestamp_utc=datetime(2026, 3, 11, 10, 0, 0)), now=now
    )
    assert result.valid is False
    assert result.status == "UNVERIFIED"
    assert "TIMESTAMP_UTC_MISSING_TZ" in result.reasons


def test_naive_source_timestamp_is_unverified(now):
    result = validate_snapshot(
        make_snapshot(source_timestamp=datetime(2026, 3, 11, 10, 0, 0)), now=now
    )
    assert result.valid is False
    assert result.status == "UNVERIFIED"
    assert "SOURCE_TIMESTAMP_MISSING_TZ" in result.reasons


def test_future_source_timestamp_is_invalid(now):
    result = validate_snapshot(
        make_snapshot(
            source_timestamp=NOW + timedelta(minutes=10), freshness_seconds=0
        ),
        now=now,
    )
    assert result.valid is False
    assert result.status == "INVALID"
    assert "SOURCE_TIMESTAMP_IN_FUTURE" in result.reasons


def test_future_timestamp_utc_is_invalid(now):
    result = validate_snapshot(
        make_snapshot(timestamp_utc=NOW + timedelta(hours=2)), now=now
    )
    assert result.valid is False
    assert "TIMESTAMP_UTC_IN_FUTURE" in result.reasons


def test_small_clock_skew_is_tolerated(now):
    result = validate_snapshot(
        make_snapshot(
            timestamp_utc=NOW + timedelta(seconds=5),
            source_timestamp=NOW + timedelta(seconds=5),
        ),
        now=now,
    )
    assert result.valid is True


# --- session date -------------------------------------------------------


def test_ancient_session_date_is_rejected(now):
    """REGRESSION: a 2019 session date on a live snapshot used to pass."""
    result = validate_snapshot(make_snapshot(session_date=datetime(2019, 1, 1).date()), now=now)
    assert result.valid is False
    assert "SESSION_DATE_TOO_OLD" in result.reasons
    assert "SESSION_DATE_TIMESTAMP_MISMATCH" in result.reasons


def test_future_session_date_is_invalid(now):
    result = validate_snapshot(make_snapshot(session_date=datetime(2026, 4, 1).date()), now=now)
    assert result.valid is False
    assert result.status == "INVALID"
    assert "SESSION_DATE_IN_FUTURE" in result.reasons


def test_session_date_slightly_behind_timestamp_is_allowed(now):
    """Weekend/holiday carry-over of one day is tolerated."""
    result = validate_snapshot(
        make_snapshot(session_date=(NOW - timedelta(days=1)).date()), now=now
    )
    assert result.valid is True


def test_session_date_uses_market_timezone(now):
    """23:00 UTC is already the next Cairo day; the session date must follow."""
    late = datetime(2026, 3, 11, 23, 0, 0, tzinfo=timezone.utc)
    result = validate_snapshot(
        make_snapshot(
            timestamp_utc=late,
            source_timestamp=late,
            session_date=datetime(2026, 3, 12).date(),
        ),
        now=late,
    )
    assert result.valid is True


def test_unknown_market_timezone_is_unverified(now):
    result = validate_snapshot(make_snapshot(market_timezone="Mars/Olympus"), now=now)
    assert result.valid is False
    assert result.status == "UNVERIFIED"
    assert "UNKNOWN_MARKET_TIMEZONE" in result.reasons


# --- price structure ----------------------------------------------------


def test_crossed_book_is_rejected(now):
    result = validate_snapshot(
        make_snapshot(bid=Decimal("10.2"), ask=Decimal("10.1")), now=now
    )
    assert result.valid is False
    assert result.status == "INVALID"
    assert "CROSSED_BID_ASK" in result.reasons


def test_inverted_high_low_is_rejected(now):
    result = validate_snapshot(
        make_snapshot(high=Decimal("9"), low=Decimal("11")), now=now
    )
    assert result.valid is False
    assert "INVALID_HIGH_LOW" in result.reasons


def test_last_outside_session_range_is_rejected(now):
    result = validate_snapshot(
        make_snapshot(last_price=Decimal("12"), high=Decimal("10.5"), low=Decimal("9.5")),
        now=now,
    )
    assert result.valid is False
    assert "LAST_OUTSIDE_SESSION_RANGE" in result.reasons


def test_open_outside_session_range_is_rejected(now):
    result = validate_snapshot(
        make_snapshot(open=Decimal("12"), high=Decimal("10.5"), low=Decimal("9.5")),
        now=now,
    )
    assert result.valid is False
    assert "OPEN_OUTSIDE_SESSION_RANGE" in result.reasons


# --- policy plumbing ----------------------------------------------------


def test_freshness_limit_override_is_honoured(now):
    snap = make_snapshot(
        freshness_seconds=300, source_timestamp=NOW - timedelta(seconds=300)
    )
    assert validate_snapshot(snap, now=now).status == "STALE"
    assert validate_snapshot(snap, max_freshness_seconds=600, now=now).valid is True


def test_custom_data_policy_is_honoured(now):
    strict = DataPolicy(max_freshness_seconds=5)
    assert validate_snapshot(make_snapshot(), policy=strict, now=now).status == "STALE"
