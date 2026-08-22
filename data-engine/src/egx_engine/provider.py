from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Sequence

from .models import DailyBar, MarketSnapshot


class MarketDataError(RuntimeError):
    pass


class MarketDataProvider(ABC):
    """Stable provider contract. Concrete providers are intentionally replaceable."""

    name: str

    @abstractmethod
    def health(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def instruments(self) -> Sequence[dict]:
        raise NotImplementedError

    @abstractmethod
    def snapshot(self, symbols: Sequence[str]) -> list[MarketSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        raise NotImplementedError


class UnconfiguredProvider(MarketDataProvider):
    """Explicit fail-closed provider used until a market-data feed is verified."""

    name = "unconfigured"

    def health(self) -> bool:
        return False

    def instruments(self) -> Sequence[dict]:
        return []

    def snapshot(self, symbols: Sequence[str]) -> list[MarketSnapshot]:
        raise MarketDataError(
            "No verified market-data provider configured. DATA_NOT_VERIFIED_NO_TRADE."
        )

    def daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        raise MarketDataError(
            "No verified market-data provider configured. Historical data unavailable."
        )
