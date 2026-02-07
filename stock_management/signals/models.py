from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Reason:
    name: str
    current: float | None
    threshold: float | None
    passed: bool


@dataclass(frozen=True, slots=True)
class Signal:
    symbol: str
    time: datetime
    freq: str
    direction: str  # Entry | Exit | Risk | Watch
    score: int
    entry_zone: tuple[float, float]
    stop_loss: float
    take_profit: tuple[float, float]  # (TP1, TP2)
    reasons: tuple[Reason, ...]
    risk_flags: tuple[str, ...] = ()

