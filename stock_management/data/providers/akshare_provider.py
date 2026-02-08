from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from ..models import Bar
from .base import DataProvider


TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


class AkshareError(RuntimeError):
    pass


def _to_ak_symbol_6(symbol: str) -> str:
    """
    Convert our symbol like 000001.SZ / 600000.SH to AkShare code strings.
    """
    if "." not in symbol:
        raise AkshareError(f"unsupported symbol format: {symbol}")
    code, suffix = symbol.split(".", 1)
    suffix = suffix.upper()
    if suffix not in ("SZ", "SH"):
        raise AkshareError(f"unsupported symbol suffix: {symbol}")
    if len(code) != 6 or not code.isdigit():
        raise AkshareError(f"unsupported symbol code: {symbol}")
    return code


def _to_ak_symbol_market(symbol: str) -> str:
    """
    Convert our symbol like 000001.SZ / 600000.SH to AkShare "sz000001"/"sh600000".
    """
    if "." not in symbol:
        raise AkshareError(f"unsupported symbol format: {symbol}")
    code, suffix = symbol.split(".", 1)
    suffix = suffix.upper()
    if suffix == "SZ":
        return f"sz{code}"
    if suffix == "SH":
        return f"sh{code}"
    raise AkshareError(f"unsupported symbol suffix: {symbol}")


def _ensure_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("start/end must be timezone-aware (Asia/Shanghai)")
    return dt.astimezone(TZ_SHANGHAI)


def _fmt_ak_dt(dt: datetime) -> str:
    dt = _ensure_tz(dt)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _df_to_bars(df, *, source: str) -> list[Bar]:
    # df columns are typically: 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 均价
    if df is None or len(df) == 0:
        return []
    cols = list(df.columns)
    if "时间" not in cols:
        raise AkshareError(f"unexpected dataframe columns: {cols}")

    out: list[Bar] = []
    for row in df.itertuples(index=False):
        # Access by column names to be robust
        d = row._asdict()
        ts_raw = d.get("时间")
        ts = ts_raw.to_pydatetime() if hasattr(ts_raw, "to_pydatetime") else ts_raw
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace(" ", "T"))
        if not isinstance(ts, datetime):
            raise AkshareError("unexpected 时间 type")
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=TZ_SHANGHAI)
        ts = ts.astimezone(TZ_SHANGHAI)

        open_ = float(d.get("开盘"))
        close = float(d.get("收盘"))
        high = float(d.get("最高"))
        low = float(d.get("最低"))
        volume = int(float(d.get("成交量")))
        amount_v = d.get("成交额")
        amount = None if amount_v is None else float(amount_v)

        out.append(Bar(ts=ts, open=open_, high=high, low=low, close=close, volume=volume, amount=amount, source=source))
    out.sort(key=lambda b: b.ts)
    return out


@dataclass(frozen=True, slots=True)
class AkshareKlineProvider(DataProvider):
    """
    AkShare-based provider.

    Notes:
    - 1m history may be limited to recent days.
    - 5m/15m/etc can have longer history and is useful for signal scan/backtest.
    """

    provider_id: str = "akshare"
    volume_unit: str = "unknown"
    source: str = "akshare"

    def fetch_1m_bars(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        start = _ensure_tz(start)
        end = _ensure_tz(end)
        if end <= start:
            return []

        try:
            import akshare as ak  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise AkshareError("akshare is not installed; install via environment.yml") from e

        code6 = _to_ak_symbol_6(symbol)
        df = ak.stock_zh_a_hist_min_em(
            symbol=code6,
            start_date=_fmt_ak_dt(start),
            end_date=_fmt_ak_dt(end),
            period="1",
            adjust="",
        )
        bars = _df_to_bars(df, source=self.source)
        bars = [b for b in bars if start <= b.ts < end]
        return bars

    def fetch_bars(self, *, freq: str, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        """
        Optional extension used by DataService.get_bars when cache coverage is insufficient.
        """
        start = _ensure_tz(start)
        end = _ensure_tz(end)
        if end <= start:
            return []

        freq = freq.strip().lower()
        if freq == "1m":
            return self.fetch_1m_bars(symbol, start, end)
        period_map = {"5m": "5", "15m": "15", "30m": "30", "60m": "60"}
        if freq not in period_map:
            raise AkshareError(f"unsupported freq: {freq}")

        try:
            import akshare as ak  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise AkshareError("akshare is not installed; install via environment.yml") from e

        code6 = _to_ak_symbol_6(symbol)
        df = ak.stock_zh_a_hist_min_em(
            symbol=code6,
            start_date=_fmt_ak_dt(start),
            end_date=_fmt_ak_dt(end),
            period=period_map[freq],
            adjust="",
        )
        bars = _df_to_bars(df, source=self.source)
        bars = [b for b in bars if start <= b.ts < end]
        return bars

    def fetch_recent_1m(self, symbol: str) -> list[Bar]:
        """
        Fallback function for some AkShare endpoints without start/end.
        Not used by default.
        """
        try:
            import akshare as ak  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise AkshareError("akshare is not installed; install via environment.yml") from e

        market_symbol = _to_ak_symbol_market(symbol)
        df = ak.stock_zh_a_minute(symbol=market_symbol, period="1", adjust="")
        if "day" not in df.columns:
            return []
        df = df.rename(
            columns={
                "day": "时间",
                "open": "开盘",
                "close": "收盘",
                "high": "最高",
                "low": "最低",
                "volume": "成交量",
            }
        )
        df["成交额"] = None
        return _df_to_bars(df, source=self.source)
