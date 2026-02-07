from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from datetime import timedelta
from zoneinfo import ZoneInfo

import requests

from ..models import Bar
from .base import DataProvider


TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


class EastmoneyError(RuntimeError):
    pass


def _to_secid(symbol: str) -> str:
    """
    Convert A-share symbol like '000001.SZ' / '600000.SH' to Eastmoney secid.
    """
    if "." not in symbol:
        raise EastmoneyError(f"unsupported symbol format: {symbol}")
    code, suffix = symbol.split(".", 1)
    suffix = suffix.upper()
    if suffix == "SZ":
        return f"0.{code}"
    if suffix == "SH":
        return f"1.{code}"
    raise EastmoneyError(f"unsupported symbol suffix: {symbol}")


def _parse_kline_row(row: str, source: str) -> Bar:
    # f51,f52,f53,f54,f55,f56,f57 => 时间,开,收,高,低,量,额
    parts = row.split(",")
    if len(parts) < 6:
        raise EastmoneyError(f"unexpected kline row: {row}")

    # Eastmoney 1m Kline timestamp is often the "minute end time".
    # Normalize to our internal convention: minute start time.
    ts_end = datetime.strptime(parts[0], "%Y-%m-%d %H:%M").replace(tzinfo=TZ_SHANGHAI)
    ts = ts_end - timedelta(minutes=1)
    open_ = float(parts[1])
    close = float(parts[2])
    high = float(parts[3])
    low = float(parts[4])
    volume = int(float(parts[5]))
    amount = float(parts[6]) if len(parts) > 6 and parts[6] not in ("", "null", "None") else None

    return Bar(ts=ts, open=open_, high=high, low=low, close=close, volume=volume, amount=amount, source=source)


@dataclass(frozen=True, slots=True)
class EastmoneyKlineProvider(DataProvider):
    api_url: str = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    source: str = "eastmoney_kline"
    provider_id: str = "eastmoney_kline"
    volume_unit: str = "unknown"
    timeout_sec: float = 15.0
    min_interval_sec: float = 0.2  # naive client-side rate limit
    max_retries: int = 3
    backoff_base_sec: float = 0.5

    def fetch_1m_bars(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start/end must be timezone-aware (Asia/Shanghai)")
        if end <= start:
            return []

        secid = _to_secid(symbol)

        params = {
            "secid": secid,
            "klt": 1,  # 1m
            "fqt": 0,  # no adjust
            "beg": 0,
            "end": 20500101,
            "lmt": 2000,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) stockManagement/0.0",
            "Referer": "https://quote.eastmoney.com/",
        }

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if self.min_interval_sec > 0:
                time.sleep(self.min_interval_sec)
            try:
                r = requests.get(self.api_url, params=params, headers=headers, timeout=self.timeout_sec)
                r.raise_for_status()
                payload: dict[str, Any] = r.json()
                data = payload.get("data")
                if not data:
                    raise EastmoneyError(f"missing data for symbol={symbol}")

                klines = data.get("klines") or []
                bars = [_parse_kline_row(str(row), source=self.source) for row in klines]
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt >= self.max_retries:
                    raise EastmoneyError(f"eastmoney fetch failed for {symbol}") from e
                time.sleep(self.backoff_base_sec * (2**attempt))
        else:
            raise EastmoneyError(f"eastmoney fetch failed for {symbol}") from last_err

        bars = [b for b in bars if start <= b.ts < end]
        bars.sort(key=lambda b: b.ts)
        return bars
