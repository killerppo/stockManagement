from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from ..models import Bar
from .base import DataProvider


TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


class TushareError(RuntimeError):
    pass


def _parse_trade_time(value: str) -> datetime:
    # Example: "2024-11-29 09:30:00"
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=TZ_SHANGHAI)


def _parse_items(fields: list[str], items: list[list[Any]], source: str) -> list[Bar]:
    idx = {name: i for i, name in enumerate(fields)}
    required = ["trade_time", "open", "high", "low", "close", "vol"]
    for name in required:
        if name not in idx:
            raise TushareError(f"missing field in response: {name}")

    out: list[Bar] = []
    for row in items:
        out.append(
            Bar(
                ts=_parse_trade_time(str(row[idx["trade_time"]])),
                open=float(row[idx["open"]]),
                high=float(row[idx["high"]]),
                low=float(row[idx["low"]]),
                close=float(row[idx["close"]]),
                volume=int(float(row[idx["vol"]])),
                amount=(float(row[idx["amount"]]) if "amount" in idx and row[idx["amount"]] is not None else None),
                source=source,
            )
        )
    out.sort(key=lambda b: b.ts)
    return out


@dataclass(frozen=True, slots=True)
class TushareProProvider(DataProvider):
    token: str
    api_url: str = "https://api.tushare.pro"
    source: str = "tushare_pro"
    provider_id: str = "tushare_pro"
    volume_unit: str = "unknown"
    timeout_sec: float = 15.0
    min_interval_sec: float = 0.0  # naive client-side rate limit

    @classmethod
    def from_env(cls) -> "TushareProProvider":
        token = os.getenv("TUSHARE_TOKEN", "").strip()
        if not token:
            raise TushareError("missing TUSHARE_TOKEN env var")
        return cls(token=token)

    def _post(self, api_name: str, params: dict[str, Any], fields: str) -> dict[str, Any]:
        payload = {"api_name": api_name, "token": self.token, "params": params, "fields": fields}
        r = requests.post(self.api_url, json=payload, timeout=self.timeout_sec)
        r.raise_for_status()
        data = r.json()
        if int(data.get("code", 0)) != 0:
            raise TushareError(f"tushare error: code={data.get('code')} msg={data.get('msg')}")
        return data

    def fetch_1m_bars(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start/end must be timezone-aware (Asia/Shanghai)")
        if end <= start:
            return []

        last_call = 0.0

        # Tushare minutes API returns a window; we still filter by [start, end) locally.
        params = {
            "ts_code": symbol,
            "freq": "1min",
            "start_date": start.astimezone(TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": end.astimezone(TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S"),
        }
        fields = "ts_code,trade_time,open,high,low,close,vol,amount"

        if self.min_interval_sec > 0:
            now = time.time()
            sleep = self.min_interval_sec - (now - last_call)
            if sleep > 0:
                time.sleep(sleep)
            last_call = time.time()

        resp = self._post(api_name="stk_mins", params=params, fields=fields)
        data = resp.get("data") or {}
        resp_fields = list(data.get("fields") or [])
        items = list(data.get("items") or [])

        bars = _parse_items(resp_fields, items, source=self.source)
        return [b for b in bars if start <= b.ts < end]
