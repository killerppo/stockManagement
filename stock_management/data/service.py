from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from datetime import timedelta

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
        freq = freq.lower().strip()
        freq_to_n = {"5m": 5, "15m": 15, "60m": 60}
        if freq not in freq_to_n:
            raise ValueError(f"unsupported freq: {freq}")

        bars_out = aggregate_1m(bars_1m, freq_to_n[freq])

        # If cache coverage is insufficient, allow provider-specific fallback for higher timeframes.
        # This is especially useful when a provider has longer history for 5m than 1m.
        if self.provider is not None and hasattr(self.provider, "fetch_bars"):
            mins = freq_to_n[freq]
            need_fallback = False
            if not bars_out:
                need_fallback = True
            else:
                if bars_out[0].ts > (start + timedelta(minutes=mins)):
                    need_fallback = True
                if bars_out[-1].ts < (end - timedelta(minutes=mins)):
                    need_fallback = True

            if need_fallback:
                try:
                    fetched = self.provider.fetch_bars(freq=freq, symbol=symbol, start=start, end=end)  # type: ignore[attr-defined]
                except Exception:
                    fetched = []
                if fetched:
                    by_ts: dict[datetime, Bar] = {b.ts: b for b in bars_out}
                    for b in fetched:
                        by_ts[b.ts] = b
                    merged = list(by_ts.values())
                    merged.sort(key=lambda b: b.ts)
                    return merged

        return bars_out
