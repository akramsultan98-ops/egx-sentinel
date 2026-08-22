"""Transactional persistence for the deterministic engine.

Nothing here computes a trading decision. It stores what
:mod:`egx_engine.validator` and :mod:`egx_engine.risk` produced, retrieves the
portfolio facts they need, and keeps the portfolio ledger consistent with the
executions reported against it.

Transaction policy: the connection is opened with autocommit disabled and this
class never commits. Commit and rollback belong to the caller, so a whole
decision — snapshot, verdict, plan — lands as one unit or not at all.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb
from pydantic import ValidationError as PydanticValidationError

from ..config import DataPolicy, RiskPolicy
from ..models import MarketSnapshot, PortfolioState, RiskPlan
from ..validator import ValidationResult
from .errors import (
    DuplicateExecutionError,
    InsufficientSharesError,
    PersistenceError,
    PortfolioStateUnavailableError,
)


class InsufficientCashError(PersistenceError):
    """A reported BUY costs more than the portfolio's recorded cash."""


def engine_version() -> str:
    try:
        return package_version("egx-engine")
    except PackageNotFoundError:  # pragma: no cover - source checkout without install
        return "unknown"


def require_utc(moment: datetime, field: str) -> datetime:
    """Reject naive datetimes and normalise everything to UTC.

    Every timestamp crossing the persistence boundary is stored in UTC. A naive
    datetime has no defined instant, so it is refused rather than assumed.
    """
    if moment.tzinfo is None:
        raise PersistenceError(f"{field} must be timezone-aware")
    return moment.astimezone(timezone.utc)


class Repository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    @contextmanager
    def _savepoint(self, name: str):
        """Scope a multi-statement operation without ever committing.

        ``Connection.transaction()`` commits when it is the outermost block,
        which would take commit authority away from the caller. An explicit
        savepoint gives the same all-or-nothing guarantee for the operation
        while leaving the surrounding transaction — and the decision to commit
        it — entirely with the caller.
        """
        with self.conn.cursor() as cur:
            cur.execute(f"SAVEPOINT {name}")
            try:
                yield cur
            except Exception:
                cur.execute(f"ROLLBACK TO SAVEPOINT {name}")
                cur.execute(f"RELEASE SAVEPOINT {name}")
                raise
            cur.execute(f"RELEASE SAVEPOINT {name}")

    # -- instruments ------------------------------------------------------

    def upsert_instrument(
        self,
        *,
        instrument_id: str,
        ticker: str,
        name: str,
        source: str,
        source_updated_at: datetime,
        isin: str | None = None,
        exchange: str = "EGX",
        sector: str | None = None,
        asset_type: str = "EQUITY",
        currency: str = "EGP",
        status: str = "ACTIVE",
    ) -> str:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO instruments (instrument_id, ticker, isin, name, exchange,
                                         sector, asset_type, currency, status, source,
                                         source_updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (instrument_id) DO UPDATE SET
                    ticker = EXCLUDED.ticker,
                    name = EXCLUDED.name,
                    sector = EXCLUDED.sector,
                    status = EXCLUDED.status,
                    source = EXCLUDED.source,
                    source_updated_at = EXCLUDED.source_updated_at
                RETURNING instrument_id
                """,
                (
                    instrument_id,
                    ticker,
                    isin,
                    name,
                    exchange,
                    sector,
                    asset_type,
                    currency,
                    status,
                    source,
                    require_utc(source_updated_at, "source_updated_at"),
                ),
            )
            return cur.fetchone()[0]

    # -- market snapshots -------------------------------------------------

    def save_snapshot(self, snapshot: MarketSnapshot) -> int:
        """Persist a snapshot idempotently.

        Re-delivery of the same tick (same instrument, source, and source
        timestamp) returns the existing id instead of writing a second row, so
        an orchestrator retry cannot inflate market history.
        """
        params = (
            snapshot.instrument_id,
            require_utc(snapshot.timestamp_utc, "timestamp_utc"),
            snapshot.market_timezone,
            snapshot.session_date,
            snapshot.last_price,
            snapshot.bid,
            snapshot.ask,
            snapshot.open,
            snapshot.high,
            snapshot.low,
            snapshot.previous_close,
            snapshot.volume,
            snapshot.traded_value_egp,
            snapshot.source,
            require_utc(snapshot.source_timestamp, "source_timestamp"),
            snapshot.freshness_seconds,
            snapshot.validation_status,
        )
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO market_snapshots (
                        instrument_id, timestamp_utc, market_timezone, session_date,
                        last_price, bid, ask, open, high, low, previous_close,
                        volume, traded_value_egp, source, source_timestamp,
                        freshness_seconds, validation_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s)
                    ON CONFLICT (instrument_id, source, source_timestamp) DO NOTHING
                    RETURNING snapshot_id
                    """,
                    params,
                )
                row = cur.fetchone()
                if row is not None:
                    return row[0]

                cur.execute(
                    """
                    SELECT snapshot_id FROM market_snapshots
                     WHERE instrument_id = %s AND source = %s AND source_timestamp = %s
                    """,
                    (snapshot.instrument_id, snapshot.source, params[14]),
                )
                return cur.fetchone()[0]
        except psycopg.Error as exc:
            raise PersistenceError(f"could not save market snapshot: {exc}") from exc

    def get_snapshot(self, snapshot_id: int) -> MarketSnapshot:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.instrument_id, i.ticker, s.timestamp_utc, s.market_timezone,
                       s.session_date, s.last_price, s.bid, s.ask, s.open, s.high,
                       s.low, s.previous_close, s.volume, s.traded_value_egp,
                       s.source, s.source_timestamp, s.freshness_seconds,
                       s.validation_status
                  FROM market_snapshots s
                  JOIN instruments i ON i.instrument_id = s.instrument_id
                 WHERE s.snapshot_id = %s
                """,
                (snapshot_id,),
            )
            row = cur.fetchone()

        if row is None:
            raise PersistenceError(f"no market snapshot with id {snapshot_id}")

        keys = (
            "instrument_id ticker timestamp_utc market_timezone session_date last_price "
            "bid ask open high low previous_close volume traded_value_egp source "
            "source_timestamp freshness_seconds validation_status"
        ).split()
        return MarketSnapshot(**dict(zip(keys, row)))

    # -- validation results -----------------------------------------------

    def save_validation_result(
        self,
        *,
        snapshot_id: int,
        result: ValidationResult,
        data_policy: DataPolicy,
        max_freshness_seconds: int,
        validated_at: datetime,
    ) -> int:
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO validation_results (
                        snapshot_id, status, reasons, max_freshness_seconds,
                        data_policy, validated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING validation_result_id
                    """,
                    (
                        snapshot_id,
                        result.status,
                        list(result.reasons),
                        max_freshness_seconds,
                        Jsonb(data_policy.model_dump(mode="json")),
                        require_utc(validated_at, "validated_at"),
                    ),
                )
                return cur.fetchone()[0]
        except psycopg.Error as exc:
            raise PersistenceError(f"could not save validation result: {exc}") from exc

    def get_validation_reasons(self, validation_result_id: int) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT status, reasons FROM validation_results WHERE validation_result_id = %s",
                (validation_result_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise PersistenceError(f"no validation result with id {validation_result_id}")
        return list(row[1])

    # -- risk plans -------------------------------------------------------

    def save_risk_plan(
        self,
        *,
        plan: RiskPlan,
        validation_result_id: int,
        instrument_id: str,
        portfolio_id: int,
        portfolio: PortfolioState,
        risk_policy: RiskPolicy,
        liquidity_gate: str,
    ) -> int:
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO risk_plans (
                        validation_result_id, instrument_id, portfolio_id, action, reason,
                        entry, stop_loss, target, shares, position_value_egp,
                        concentration_fraction, fees_egp, risk_egp, reward_egp,
                        risk_reward, risk_reward_gross, equity_egp_at_decision,
                        cash_egp_at_decision, open_positions_at_decision, risk_policy,
                        liquidity_gate, engine_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s)
                    RETURNING risk_plan_id
                    """,
                    (
                        validation_result_id,
                        instrument_id,
                        portfolio_id,
                        plan.action,
                        plan.reason,
                        plan.entry,
                        plan.stop_loss,
                        plan.target,
                        plan.shares,
                        plan.position_value_egp,
                        plan.concentration_fraction,
                        plan.fees_egp,
                        plan.risk_egp,
                        plan.reward_egp,
                        plan.risk_reward,
                        plan.risk_reward_gross,
                        portfolio.equity_egp,
                        portfolio.cash_egp,
                        portfolio.open_positions,
                        Jsonb(risk_policy.model_dump(mode="json")),
                        liquidity_gate,
                        engine_version(),
                    ),
                )
                return cur.fetchone()[0]
        except psycopg.Error as exc:
            raise PersistenceError(f"could not save risk plan: {exc}") from exc

    def get_risk_plan(self, risk_plan_id: int) -> RiskPlan:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT i.ticker, r.action, r.entry, r.stop_loss, r.target, r.shares,
                       r.position_value_egp, r.concentration_fraction, r.fees_egp,
                       r.risk_egp, r.reward_egp, r.risk_reward, r.risk_reward_gross,
                       s.source, s.timestamp_utc, r.reason
                  FROM risk_plans r
                  JOIN instruments i ON i.instrument_id = r.instrument_id
                  JOIN validation_results v ON v.validation_result_id = r.validation_result_id
                  JOIN market_snapshots s ON s.snapshot_id = v.snapshot_id
                 WHERE r.risk_plan_id = %s
                """,
                (risk_plan_id,),
            )
            row = cur.fetchone()

        if row is None:
            raise PersistenceError(f"no risk plan with id {risk_plan_id}")

        keys = (
            "ticker action entry stop_loss target shares position_value_egp "
            "concentration_fraction fees_egp risk_egp reward_egp risk_reward "
            "risk_reward_gross snapshot_source snapshot_timestamp_utc reason"
        ).split()
        return RiskPlan(**dict(zip(keys, row)))

    def get_decision_audit_trail(self, risk_plan_id: int) -> dict[str, Any]:
        """Return the full chain behind one decision.

        Source data -> validation verdict and findings -> risk calculation.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.risk_plan_id, r.action, r.reason, r.engine_version,
                       r.risk_policy, r.liquidity_gate,
                       r.equity_egp_at_decision, r.cash_egp_at_decision,
                       r.open_positions_at_decision,
                       v.validation_result_id, v.status, v.reasons, v.data_policy,
                       v.validated_at,
                       s.snapshot_id, s.source, s.source_timestamp, s.timestamp_utc,
                       s.last_price, s.freshness_seconds, s.validation_status
                  FROM risk_plans r
                  JOIN validation_results v ON v.validation_result_id = r.validation_result_id
                  JOIN market_snapshots s ON s.snapshot_id = v.snapshot_id
                 WHERE r.risk_plan_id = %s
                """,
                (risk_plan_id,),
            )
            row = cur.fetchone()

        if row is None:
            raise PersistenceError(f"no risk plan with id {risk_plan_id}")

        return {
            "decision": {
                "risk_plan_id": row[0],
                "action": row[1],
                "reason": row[2],
                "engine_version": row[3],
                "risk_policy": row[4],
                "liquidity_gate": row[5],
                "equity_egp_at_decision": row[6],
                "cash_egp_at_decision": row[7],
                "open_positions_at_decision": row[8],
            },
            "validation": {
                "validation_result_id": row[9],
                "status": row[10],
                "reasons": list(row[11]),
                "data_policy": row[12],
                "validated_at": row[13],
            },
            "source_data": {
                "snapshot_id": row[14],
                "source": row[15],
                "source_timestamp": row[16],
                "timestamp_utc": row[17],
                "last_price": row[18],
                "freshness_seconds": row[19],
                "validation_status": row[20],
            },
        }

    # -- portfolio --------------------------------------------------------

    def create_portfolio(
        self,
        *,
        name: str,
        initial_capital_egp: Decimal,
        cash_egp: Decimal | None = None,
        risk_budget_pct: Decimal = Decimal("1.5"),
    ) -> int:
        """Create a portfolio.

        ``risk_budget_pct`` is stored in percent because the column is
        percent-typed; the canonical fraction lives in
        :mod:`egx_engine.config`.
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO portfolio (name, initial_capital_egp, cash_egp,
                                           risk_budget_pct)
                    VALUES (%s, %s, %s, %s)
                    RETURNING portfolio_id
                    """,
                    (
                        name,
                        initial_capital_egp,
                        initial_capital_egp if cash_egp is None else cash_egp,
                        risk_budget_pct,
                    ),
                )
                return cur.fetchone()[0]
        except psycopg.Error as exc:
            raise PersistenceError(f"could not create portfolio: {exc}") from exc

    def get_portfolio_state(self, portfolio_id: int) -> PortfolioState:
        """Read the deterministic sizing inputs from the ``portfolio_state`` view.

        Raises :class:`PortfolioStateUnavailableError` when equity cannot be
        established — for example when an open position has no validated price.
        Unknown equity must never be guessed.
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cash_egp, total_equity_egp, open_positions, unpriced_positions
                      FROM portfolio_state
                     WHERE portfolio_id = %s
                    """,
                    (portfolio_id,),
                )
                row = cur.fetchone()
        except psycopg.Error as exc:
            raise PersistenceError(f"could not read portfolio state: {exc}") from exc

        if row is None:
            raise PortfolioStateUnavailableError(f"no portfolio with id {portfolio_id}")

        cash, equity, open_positions, unpriced = row
        if equity is None:
            raise PortfolioStateUnavailableError(
                f"portfolio {portfolio_id} has {unpriced} open position(s) with no "
                "validated price; equity is unknown"
            )

        try:
            return PortfolioState(
                equity_egp=equity, cash_egp=cash, open_positions=open_positions
            )
        except PydanticValidationError as exc:
            raise PortfolioStateUnavailableError(
                f"portfolio {portfolio_id} state is not usable for sizing: {exc}"
            ) from exc

    def get_open_positions(self, portfolio_id: int) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT position_id, instrument_id, shares, average_entry,
                       realized_pnl_egp, status, opened_at, closed_at
                  FROM portfolio_positions
                 WHERE portfolio_id = %s AND status = 'OPEN'
                 ORDER BY instrument_id
                """,
                (portfolio_id,),
            )
            keys = (
                "position_id instrument_id shares average_entry realized_pnl_egp "
                "status opened_at closed_at"
            ).split()
            return [dict(zip(keys, row)) for row in cur.fetchall()]

    def get_position(self, portfolio_id: int, instrument_id: str) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT position_id, instrument_id, shares, average_entry,
                       realized_pnl_egp, status, opened_at, closed_at
                  FROM portfolio_positions
                 WHERE portfolio_id = %s AND instrument_id = %s AND status = 'OPEN'
                """,
                (portfolio_id, instrument_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        keys = (
            "position_id instrument_id shares average_entry realized_pnl_egp "
            "status opened_at closed_at"
        ).split()
        return dict(zip(keys, row))

    # -- executions -------------------------------------------------------

    def record_execution(
        self,
        *,
        portfolio_id: int,
        instrument_id: str,
        side: str,
        shares: int,
        execution_price: Decimal,
        execution_time: datetime,
        idempotency_key: str,
        fees_egp: Decimal = Decimal("0"),
        source: str = "user_reported",
        telegram_message_id: str | None = None,
    ) -> int:
        """Record a manually executed fill and move the portfolio to match.

        The execution row, the position, and the cash/realised-P&L ledger all
        move together inside one savepoint: either the whole fill is applied or
        none of it is.
        """
        if side not in ("BUY", "SELL"):
            raise PersistenceError(f"unknown execution side {side!r}")
        if shares <= 0:
            raise PersistenceError("execution shares must be positive")

        executed_at = require_utc(execution_time, "execution_time")

        try:
            with self._savepoint("egx_record_execution") as cur:
                cur.execute(
                    """
                    INSERT INTO executions (
                        portfolio_id, instrument_id, side, shares, execution_price,
                        execution_time, fees_egp, source, telegram_message_id,
                        idempotency_key)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING execution_id
                    """,
                    (
                        portfolio_id,
                        instrument_id,
                        side,
                        shares,
                        execution_price,
                        executed_at,
                        fees_egp,
                        source,
                        telegram_message_id,
                        idempotency_key,
                    ),
                )
                execution_id = cur.fetchone()[0]

                if side == "BUY":
                    self._apply_buy(
                        cur, portfolio_id, instrument_id, shares,
                        execution_price, fees_egp, executed_at,
                    )
                else:
                    self._apply_sell(
                        cur, portfolio_id, instrument_id, shares,
                        execution_price, fees_egp, executed_at,
                    )

                cur.execute(
                    "UPDATE portfolio SET updated_at = now() WHERE portfolio_id = %s",
                    (portfolio_id,),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateExecutionError(
                f"execution with idempotency key {idempotency_key!r} was already recorded"
            ) from exc
        except psycopg.Error as exc:
            raise PersistenceError(f"could not record execution: {exc}") from exc

        return execution_id

    def _apply_buy(
        self, cur, portfolio_id, instrument_id, shares, price, fees, executed_at
    ) -> None:
        cost = price * Decimal(shares) + fees

        cur.execute(
            "SELECT cash_egp FROM portfolio WHERE portfolio_id = %s FOR UPDATE",
            (portfolio_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise PersistenceError(f"no portfolio with id {portfolio_id}")
        if row[0] < cost:
            raise InsufficientCashError(
                f"reported BUY costs {cost} EGP but the portfolio holds {row[0]} EGP"
            )

        cur.execute(
            "UPDATE portfolio SET cash_egp = cash_egp - %s WHERE portfolio_id = %s",
            (cost, portfolio_id),
        )

        cur.execute(
            """
            SELECT position_id, shares, average_entry
              FROM portfolio_positions
             WHERE portfolio_id = %s AND instrument_id = %s AND status = 'OPEN'
             FOR UPDATE
            """,
            (portfolio_id, instrument_id),
        )
        existing = cur.fetchone()

        if existing is None:
            cur.execute(
                """
                INSERT INTO portfolio_positions (
                    portfolio_id, instrument_id, shares, average_entry, opened_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (portfolio_id, instrument_id, shares, price, executed_at),
            )
            return

        position_id, held, average_entry = existing
        new_shares = held + shares
        # Cost-basis average excludes fees; fees stay visible on the execution
        # rows so the entry price is never quietly inflated.
        new_average = (average_entry * Decimal(held) + price * Decimal(shares)) / Decimal(
            new_shares
        )
        cur.execute(
            """
            UPDATE portfolio_positions
               SET shares = %s, average_entry = %s, updated_at = now()
             WHERE position_id = %s
            """,
            (new_shares, new_average, position_id),
        )

    def _apply_sell(
        self, cur, portfolio_id, instrument_id, shares, price, fees, executed_at
    ) -> None:
        cur.execute(
            """
            SELECT position_id, shares, average_entry
              FROM portfolio_positions
             WHERE portfolio_id = %s AND instrument_id = %s AND status = 'OPEN'
             FOR UPDATE
            """,
            (portfolio_id, instrument_id),
        )
        existing = cur.fetchone()
        if existing is None:
            raise InsufficientSharesError(
                f"no open position in {instrument_id} to sell"
            )

        position_id, held, average_entry = existing
        if shares > held:
            raise InsufficientSharesError(
                f"reported SELL of {shares} shares exceeds the {held} held in "
                f"{instrument_id}"
            )

        proceeds = price * Decimal(shares) - fees
        realized = (price - average_entry) * Decimal(shares) - fees
        remaining = held - shares

        cur.execute(
            """
            UPDATE portfolio_positions
               SET shares = %s,
                   realized_pnl_egp = realized_pnl_egp + %s,
                   status = CASE WHEN %s = 0 THEN 'CLOSED' ELSE status END,
                   closed_at = CASE WHEN %s = 0 THEN %s ELSE closed_at END,
                   updated_at = now()
             WHERE position_id = %s
            """,
            (remaining, realized, remaining, remaining, executed_at, position_id),
        )

        cur.execute(
            """
            UPDATE portfolio
               SET cash_egp = cash_egp + %s,
                   realized_pnl_egp = realized_pnl_egp + %s
             WHERE portfolio_id = %s
            """,
            (proceeds, realized, portfolio_id),
        )

    def get_executions(self, portfolio_id: int) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT execution_id, instrument_id, side, shares, execution_price,
                       execution_time, fees_egp, source, idempotency_key
                  FROM executions
                 WHERE portfolio_id = %s
                 ORDER BY execution_time, execution_id
                """,
                (portfolio_id,),
            )
            keys = (
                "execution_id instrument_id side shares execution_price execution_time "
                "fees_egp source idempotency_key"
            ).split()
            return [dict(zip(keys, row)) for row in cur.fetchall()]
