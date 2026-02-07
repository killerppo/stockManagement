from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BreakoutParams:
    lookback: int = 20
    vol_factor: float = 1.5
    atr_buffer_k: float = 0.3
    pct_buffer: float = 0.002
    swing_lookback: int = 20

