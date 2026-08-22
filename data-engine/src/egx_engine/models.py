from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ValidationStatus = Literal["VALID", "STALE", "INVALID", "UNVERIFIED"]


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    ticker: str
    timestamp_utc: datetime
    market_timezone: str = "Africa/Cairo"
    session_date: date
    last_price: Decimal = Field(gt=0)
    bid: Decimal | None = Field(default=None, gt=0)
    ask: Decimal | None = Field(default=None, gt=0)
    open: Decimal | None = Field(default=None, gt=0)
    high: Decimal | None = Field(default=None, gt=0)
    low: Decimal | None = Field(default=None, gt=0)
    previous_close: Decimal | None = Field(default=None, gt=0)
    volume: int | None = Field(default=None, ge=0)
    traded_value_egp: Decimal | None = Field(default=None, ge=0)
    source: str
    source_timestamp: datetime
    freshness_seconds: int = Field(ge=0)
    validation_status: ValidationStatus = "UNVERIFIED"


class DailyBar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    session_date: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)
    source: str


class RiskPlan(BaseModel):
    ticker: str
    action: Literal["BUY", "NO_TRADE"]
    entry: Decimal | None = None
    stop_loss: Decimal | None = None
    target: Decimal | None = None
    shares: int = 0
    risk_egp: Decimal = Decimal("0")
    reward_egp: Decimal = Decimal("0")
    risk_reward: Decimal = Decimal("0")
    reason: str
