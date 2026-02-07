from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .aggregate import aggregate_1m
from .models import Bar
from .providers.base import DataProvider
from .store.sqlite_store import SQLiteBarStore
from .quality import find_gaps


@dataclass(frozen=True, slots=True)
class DataService:
    provider: DataProvider | None
    store: SQLiteBarStore

    @classmethod
    def with_default_store(cls, provider: DataProvider, data_dir: Path = Path("data")) -> "DataService":
        return cls(provider=provider, store=SQLiteBarStore(path=data_dir / "bars.sqlite"))

    def refresh_1m(self, symbol: str, start: datetime, end: datetime) -> int:
        if self.provider is None:
            raise RuntimeError("provider is not configured")
        bars = self.provider.fetch_1m_bars(symbol=symbol, start=start, end=end)
        return self.store.upsert_1m(symbol=symbol, bars=bars)

    def ensure_1m(self, symbol: str, start: datetime, end: datetime, max_missing: int = 0) -> int:
        cached = self.store.load_1m(symbol=symbol, start=start, end=end)
        gaps = find_gaps(symbol, cached, start=start, end=end)
        if len(gaps) <= max_missing:
            return 0
        return self.refresh_1m(symbol=symbol, start=start, end=end)

    def get_bars(self, symbol: str, freq: str, start: datetime, end: datetime) -> list[Bar]:
        bars_1m = self.store.load_1m(symbol=symbol, start=start, end=end)
        if freq == "1m":
            return bars_1m
        if freq == "5m":
            return aggregate_1m(bars_1m, 5)
        if freq == "15m":
            return aggregate_1m(bars_1m, 15)
        if freq == "60m":
            return aggregate_1m(bars_1m, 60)
        raise ValueError(f"unsupported freq: {freq}")
