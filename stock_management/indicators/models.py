from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndicatorParams:
    ema_periods: tuple[int, ...] = (5, 10, 20)
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    atr_period: int = 14
    boll_period: int = 20
    boll_n_std: float = 2.0
    vol_sma_period: int = 20

