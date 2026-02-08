from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TradeResult:
    symbol: str
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    return_pct: float
    r_multiple: float | None
    outcome: str  # tp | sl | timeout
    entry_mode: str
    fee_bps: float
    slippage_bps: float
    fill_bars: int
    hold_bars: int
    tp_level: int


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    scope: str
    trades: list[TradeResult]
    signals: int
    skipped: int
    wins: int
    win_rate: float
    avg_return: float
    avg_r: float | None
    avg_win: float | None
    avg_loss: float | None
    expectancy: float | None
    profit_factor: float | None
    max_drawdown: float


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    metric: str
    best_params: dict[str, float | int]
    best_value: float
    summary: BacktestSummary
