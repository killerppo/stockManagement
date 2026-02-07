from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..models import Bar
from .base import DataProvider


class ProviderExhaustedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FallbackProvider(DataProvider):
    providers: tuple[DataProvider, ...]
    provider_id: str = "fallback"
    volume_unit: str = "unknown"

    def fetch_1m_bars(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        errors: list[Exception] = []
        for provider in self.providers:
            try:
                bars = provider.fetch_1m_bars(symbol=symbol, start=start, end=end)
                if bars:
                    return bars
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        if errors:
            raise ProviderExhaustedError(f"all providers failed for {symbol}") from errors[-1]
        return []

