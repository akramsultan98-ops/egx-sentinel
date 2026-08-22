"""Deterministic market-snapshot validation.

Design rules:

* **Non-mutating.** ``validate_snapshot`` never writes to its argument. It
  returns a :class:`ValidationResult` carrying a *copy* of the snapshot stamped
  with the resulting status, so callers cannot accidentally launder an
  unvalidated object into a validated one.
* **Deterministic.** "Now" is an injectable parameter. Given the same inputs the
  function always produces the same output.
* **Fail closed.** Anything that cannot be positively verified degrades the
  status. Only a snapshot with zero findings is ``VALID``.
* **Self-reported freshness is a claim, not evidence.** ``freshness_seconds``
  is always cross-checked against the age implied by ``source_timestamp``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import DEFAULT_DATA_POLICY, DataPolicy
from .models import MarketSnapshot, ValidationStatus

# Findings that mean the record contradicts itself or the clock. Nothing about
# it can be trusted, including its age.
INVALID_REASONS: frozenset[str] = frozenset(
    {
        "INVALID_LAST_PRICE",
        "CROSSED_BID_ASK",
        "INVALID_HIGH_LOW",
        "LAST_OUTSIDE_SESSION_RANGE",
        "OPEN_OUTSIDE_SESSION_RANGE",
        "SOURCE_TIMESTAMP_IN_FUTURE",
        "TIMESTAMP_UTC_IN_FUTURE",
        "FRESHNESS_MISREPORTED",
        "SESSION_DATE_IN_FUTURE",
        "SESSION_DATE_TIMESTAMP_MISMATCH",
    }
)

# Findings that mean provenance could not be established. The data may be fine;
# we simply cannot prove it, which is the same thing as unusable.
UNVERIFIED_REASONS: frozenset[str] = frozenset(
    {
        "SOURCE_TIMESTAMP_MISSING_TZ",
        "TIMESTAMP_UTC_MISSING_TZ",
        "UNKNOWN_MARKET_TIMEZONE",
    }
)

# Findings that mean the record is internally consistent but too old to trade.
STALE_REASONS: frozenset[str] = frozenset(
    {
        "STALE_DATA",
        "STALE_SOURCE_TIMESTAMP",
        "SESSION_DATE_TOO_OLD",
    }
)


class ValidationResult:
    """Outcome of validating one snapshot.

    ``snapshot`` is a stamped copy; the input object is left untouched.
    """

    __slots__ = ("status", "reasons", "snapshot")

    def __init__(
        self,
        status: ValidationStatus,
        reasons: list[str],
        snapshot: MarketSnapshot,
    ):
        self.status: ValidationStatus = status
        self.reasons = reasons
        self.snapshot = snapshot

    @property
    def valid(self) -> bool:
        """True only for a fully verified, fresh, self-consistent snapshot."""
        return self.status == "VALID"

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"ValidationResult(status={self.status!r}, reasons={self.reasons!r})"


def _classify(reasons: list[str]) -> ValidationStatus:
    """Map findings to a status, most severe first.

    INVALID > UNVERIFIED > STALE > VALID. Severity ordering matters: a stale
    record that *also* contradicts itself must not be softened to STALE, and an
    unprovable record must never be reported as merely old.
    """
    if not reasons:
        return "VALID"
    if any(r in INVALID_REASONS for r in reasons):
        return "INVALID"
    if any(r in UNVERIFIED_REASONS for r in reasons):
        return "UNVERIFIED"
    if any(r in STALE_REASONS for r in reasons):
        return "STALE"
    return "INVALID"


def _market_date(moment: datetime, tz: ZoneInfo) -> date:
    return moment.astimezone(tz).date()


def validate_snapshot(
    snapshot: MarketSnapshot,
    max_freshness_seconds: int | None = None,
    *,
    policy: DataPolicy = DEFAULT_DATA_POLICY,
    now: datetime | None = None,
) -> ValidationResult:
    """Validate one market snapshot without mutating it.

    Args:
        snapshot: the record to check.
        max_freshness_seconds: optional override of ``policy.max_freshness_seconds``.
        policy: deterministic thresholds (see :mod:`egx_engine.config`).
        now: injected clock for determinism. Defaults to the current UTC time.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware")

    freshness_limit = (
        policy.max_freshness_seconds
        if max_freshness_seconds is None
        else max_freshness_seconds
    )

    reasons: list[str] = []

    # --- price/structure consistency -------------------------------------
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

    # --- provider-reported freshness --------------------------------------
    if snapshot.freshness_seconds > freshness_limit:
        reasons.append("STALE_DATA")

    # --- timestamps -------------------------------------------------------
    if snapshot.timestamp_utc.tzinfo is None:
        reasons.append("TIMESTAMP_UTC_MISSING_TZ")
    elif (snapshot.timestamp_utc - now).total_seconds() > policy.future_tolerance_seconds:
        reasons.append("TIMESTAMP_UTC_IN_FUTURE")

    if snapshot.source_timestamp.tzinfo is None:
        reasons.append("SOURCE_TIMESTAMP_MISSING_TZ")
    else:
        actual_age_seconds = (now - snapshot.source_timestamp).total_seconds()

        if -actual_age_seconds > policy.future_tolerance_seconds:
            reasons.append("SOURCE_TIMESTAMP_IN_FUTURE")
        else:
            # The provider's claim is only accepted if the evidence agrees.
            # A feed that reports "5 seconds old" for a three-hour-old tick is
            # not stale, it is dishonest, and must not be treated as tradeable.
            if (
                abs(actual_age_seconds - snapshot.freshness_seconds)
                > policy.freshness_tolerance_seconds
            ):
                reasons.append("FRESHNESS_MISREPORTED")

            if actual_age_seconds > freshness_limit + policy.freshness_tolerance_seconds:
                reasons.append("STALE_SOURCE_TIMESTAMP")

    # --- session date sanity ----------------------------------------------
    try:
        market_tz = ZoneInfo(snapshot.market_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        market_tz = None
        reasons.append("UNKNOWN_MARKET_TIMEZONE")

    if market_tz is not None:
        today_market = _market_date(now, market_tz)

        if snapshot.session_date > today_market:
            reasons.append("SESSION_DATE_IN_FUTURE")
        elif (today_market - snapshot.session_date).days > policy.max_session_age_days:
            reasons.append("SESSION_DATE_TOO_OLD")

        if snapshot.timestamp_utc.tzinfo is not None:
            gap_days = abs(
                (_market_date(snapshot.timestamp_utc, market_tz) - snapshot.session_date).days
            )
            if gap_days > policy.max_session_timestamp_gap_days:
                reasons.append("SESSION_DATE_TIMESTAMP_MISMATCH")

    status = _classify(reasons)
    stamped = snapshot.model_copy(update={"validation_status": status})
    return ValidationResult(status=status, reasons=reasons, snapshot=stamped)
