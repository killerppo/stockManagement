from __future__ import annotations

import math
from collections.abc import Iterable
from statistics import mean, pstdev


def sma(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    window_sum = sum(values[:period])
    out[period - 1] = window_sum / period
    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        out[i] = window_sum / period
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(values)
    if not values:
        return out
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: list[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))

    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float | None], list[float | None], list[float | None]]:
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("periods must be > 0")
    if fast >= slow:
        raise ValueError("fast must be < slow")

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is None or ema_slow[i] is None:
            continue
        dif[i] = float(ema_fast[i] - ema_slow[i])

    dif_values: list[float] = [d for d in dif if d is not None]
    dea_raw = ema(dif_values, signal) if dif_values else []
    dea: list[float | None] = [None] * len(closes)
    hist: list[float | None] = [None] * len(closes)

    # align dea_raw to original index: first dif index corresponds to slow-1
    dif_first_idx = next((i for i, d in enumerate(dif) if d is not None), None)
    if dif_first_idx is None:
        return dif, dea, hist

    for j, v in enumerate(dea_raw):
        idx = dif_first_idx + j
        if idx >= len(closes):
            break
        dea[idx] = v
        if dif[idx] is not None and dea[idx] is not None:
            hist[idx] = (dif[idx] - dea[idx]) * 2.0

    return dif, dea, hist


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("high/low/close must have same length")
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out

    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    # Seed as SMA of first `period` TRs (which correspond to indices 1..period)
    seed = sum(trs[:period]) / period
    out[period] = seed
    prev = seed
    for i in range(period + 1, len(closes)):
        tr = trs[i - 1]
        prev = (prev * (period - 1) + tr) / period
        out[i] = prev
    return out


def boll(closes: list[float], period: int = 20, n_std: float = 2.0) -> tuple[list[float | None], list[float | None], list[float | None]]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if n_std <= 0:
        raise ValueError("n_std must be > 0")
    upper: list[float | None] = [None] * len(closes)
    mid: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    if len(closes) < period:
        return upper, mid, lower

    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        m = mean(window)
        s = pstdev(window)  # population std
        mid[i] = m
        upper[i] = m + n_std * s
        lower[i] = m - n_std * s
    return upper, mid, lower


def vol_sma(volumes: list[int], period: int = 20) -> list[float | None]:
    vals = [float(v) for v in volumes]
    return sma(vals, period)

