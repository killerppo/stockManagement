from __future__ import annotations

from stock_management.data.models import Bar
from stock_management.indicators import IndicatorParams, compute_all

from ..models import Reason, Signal
from ..params import BreakoutParams


def _calc_signal_at_index(
    *,
    symbol: str,
    bars_5m: list[Bar],
    i: int,
    ind: dict[str, list[float | None]],
    ind_params: IndicatorParams,
    params: BreakoutParams,
) -> Signal | None:
    last = bars_5m[i]
    if i < params.lookback:
        return None

    prev_window = bars_5m[i - params.lookback : i]
    breakout_level = max(b.high for b in prev_window)

    atr_key = f"atr_{ind_params.atr_period}"
    vol_ma_key = f"vol_sma_{ind_params.vol_sma_period}"
    atr_v = (ind.get(atr_key) or [None] * len(bars_5m))[i]
    vol_ma_v = (ind.get(vol_ma_key) or [None] * len(bars_5m))[i]

    vol_ok = False
    vol_threshold = None
    if vol_ma_v is not None and vol_ma_v > 0:
        vol_threshold = float(vol_ma_v) * params.vol_factor
        vol_ok = last.volume > vol_threshold

    price_ok = last.close > breakout_level

    reasons = (
        Reason("breakout_level", current=last.close, threshold=breakout_level, passed=price_ok),
        Reason("vol_factor", current=float(last.volume), threshold=vol_threshold, passed=vol_ok),
    )

    if not (price_ok and vol_ok):
        return None

    trigger = breakout_level
    buffer = 0.0
    if atr_v is not None:
        buffer = max(buffer, params.atr_buffer_k * float(atr_v))
    buffer = max(buffer, params.pct_buffer * trigger)

    entry_low = trigger
    entry_high = trigger + buffer
    entry_mid = (entry_low + entry_high) / 2.0

    if i < params.swing_lookback:
        return None
    swing_window = bars_5m[i - params.swing_lookback + 1 : i + 1]
    swing_low = min(b.low for b in swing_window)
    stop_loss = swing_low - buffer

    r = entry_mid - stop_loss
    if r <= 0:
        return None
    tp1 = entry_mid + 1.0 * r
    tp2 = entry_mid + 2.0 * r

    score = 70
    if atr_v is not None and atr_v > 0 and buffer / float(atr_v) >= 0.3:
        score += 5
    score = max(0, min(100, score))

    return Signal(
        symbol=symbol,
        time=last.ts,
        freq="5m",
        direction="Entry",
        score=score,
        entry_zone=(float(entry_low), float(entry_high)),
        stop_loss=float(stop_loss),
        take_profit=(float(tp1), float(tp2)),
        reasons=reasons,
        risk_flags=(),
    )


def breakout_entry_5m(
    *,
    symbol: str,
    bars_5m: list[Bar],
    ind_params: IndicatorParams | None = None,
    params: BreakoutParams | None = None,
) -> Signal | None:
    if params is None:
        params = BreakoutParams()
    if ind_params is None:
        ind_params = IndicatorParams()

    if len(bars_5m) < max(params.lookback + 1, params.swing_lookback + 1):
        return None

    ind = compute_all(bars_5m, ind_params)
    return _calc_signal_at_index(
        symbol=symbol,
        bars_5m=bars_5m,
        i=len(bars_5m) - 1,
        ind=ind,
        ind_params=ind_params,
        params=params,
    )


def breakout_scan_5m(
    *,
    symbol: str,
    bars_5m: list[Bar],
    ind_params: IndicatorParams | None = None,
    params: BreakoutParams | None = None,
) -> list[Signal]:
    if params is None:
        params = BreakoutParams()
    if ind_params is None:
        ind_params = IndicatorParams()
    if len(bars_5m) < max(params.lookback + 1, params.swing_lookback + 1):
        return []

    ind = compute_all(bars_5m, ind_params)
    out: list[Signal] = []
    for i in range(len(bars_5m)):
        sig = _calc_signal_at_index(
            symbol=symbol,
            bars_5m=bars_5m,
            i=i,
            ind=ind,
            ind_params=ind_params,
            params=params,
        )
        if sig is not None:
            out.append(sig)
    return out
