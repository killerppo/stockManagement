from __future__ import annotations

from stock_management.data.models import Bar

from .models import IndicatorParams
from .ta import atr, boll, ema, macd, rsi, sma, vol_sma


def compute_all(bars: list[Bar], params: IndicatorParams) -> dict[str, list[float | None]]:
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    volumes = [b.volume for b in bars]

    out: dict[str, list[float | None]] = {}

    for p in params.ema_periods:
        out[f"ema_{p}"] = ema(closes, p)

    dif, dea, hist = macd(closes, fast=params.macd_fast, slow=params.macd_slow, signal=params.macd_signal)
    out["macd_dif"] = dif
    out["macd_dea"] = dea
    out["macd_hist"] = hist

    out[f"rsi_{params.rsi_period}"] = rsi(closes, params.rsi_period)
    out[f"atr_{params.atr_period}"] = atr(highs, lows, closes, params.atr_period)

    upper, mid, lower = boll(closes, period=params.boll_period, n_std=params.boll_n_std)
    out[f"boll_upper_{params.boll_period}"] = upper
    out[f"boll_mid_{params.boll_period}"] = mid
    out[f"boll_lower_{params.boll_period}"] = lower

    out[f"vol_sma_{params.vol_sma_period}"] = vol_sma(volumes, period=params.vol_sma_period)

    return out

