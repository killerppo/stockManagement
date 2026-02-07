from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..models import Bar
from .base import DataProvider


TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class CsvProvider(DataProvider):
    root_dir: Path
    source: str = "csv"
    provider_id: str = "csv"
    volume_unit: str = "unknown"

    def fetch_1m_bars(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        path = self.root_dir / f"{symbol}.csv"
        if not path.exists():
            return []

        out: list[Bar] = []
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = datetime.fromisoformat(row["ts"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=TZ_SHANGHAI)
                if not (start <= ts < end):
                    continue
                out.append(
                    Bar(
                        ts=ts,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(row["volume"]),
                        amount=(float(row["amount"]) if row.get("amount") not in (None, "", "null", "None") else None),
                        source=self.source,
                    )
                )
        out.sort(key=lambda b: b.ts)
        return out
