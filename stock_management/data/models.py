from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Bar:
    ts: datetime  # Asia/Shanghai, minute start time
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float | None
    source: str

