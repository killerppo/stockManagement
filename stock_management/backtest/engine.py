from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from math import inf

from stock_management.data.models import Bar
from stock_management.indicators import IndicatorParams
from stock_management.signals import BreakoutParams, breakout_scan_5m

from .models import BacktestSummary, OptimizationResult, TradeResult


def _calc_shares_from_cash(*, position_cash_cny: float, entry_price: float) -> int:
    cash = float(position_cash_cny)
    if cash <= 0:
        return 0
    price = float(entry_price)
    if price <= 0:
        return 0
    lots = int(cash // (price * 100.0))
    return max(0, lots * 100)


def _max_drawdown(returns: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in returns:
        equity += r
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _summarize(
    *,
    scope: str,
    trades: list[TradeResult],
    signals: int,
    skipped: int,
) -> BacktestSummary:
    if not trades:
        return BacktestSummary(
            scope=scope,
            trades=[],
            signals=signals,
            skipped=skipped,
            wins=0,
            win_rate=0.0,
            avg_return=0.0,
            avg_r=None,
            avg_win=None,
            avg_loss=None,
            expectancy=None,
            profit_factor=None,
            max_drawdown=0.0,
        )

    wins = [t for t in trades if t.return_pct > 0]
    losses = [t for t in trades if t.return_pct < 0]
    win_rate = len(wins) / len(trades)
    avg_return = sum(t.return_pct for t in trades) / len(trades)
    r_vals = [t.r_multiple for t in trades if t.r_multiple is not None]
    avg_r = sum(r_vals) / len(r_vals) if r_vals else None
    avg_win = (sum(t.return_pct for t in wins) / len(wins)) if wins else None
    avg_loss = (sum(t.return_pct for t in losses) / len(losses)) if losses else None
    expectancy = None
    if avg_win is not None and avg_loss is not None:
        expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    win_sum = sum(t.return_pct for t in wins)
    loss_sum = sum(t.return_pct for t in losses)
    if losses:
        profit_factor = win_sum / abs(loss_sum)
    else:
        profit_factor = inf if wins else None

    max_dd = _max_drawdown([t.return_pct for t in trades])

    return BacktestSummary(
        scope=scope,
        trades=trades,
        signals=signals,
        skipped=skipped,
        wins=len(wins),
        win_rate=win_rate,
        avg_return=avg_return,
        avg_r=avg_r,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=expectancy,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
    )


def summarize_trades(
    *,
    scope: str,
    trades: list[TradeResult],
    signals: int,
    skipped: int,
) -> BacktestSummary:
    return _summarize(scope=scope, trades=trades, signals=signals, skipped=skipped)


def _simulate_trade(
    *,
    symbol: str,
    bars_5m: list[Bar],
    signal_index: int,
    signal_time: datetime,
    entry_mid: float,
    entry_low: float,
    entry_high: float,
    entry_mode: str,
    stop_loss: float,
    take_profit: float,
    fill_bars: int,
    hold_bars: int,
    exit_priority: str,
    fee_bps: float,
    slippage_bps: float,
    fee_buy_cny: float,
    fee_sell_cny: float,
    position_cash_cny: float,
    tp_level: int,
) -> TradeResult | None:
    fill_bars = max(1, fill_bars)
    hold_bars = max(1, hold_bars)

    entry_mode = entry_mode.lower().strip()
    if entry_mode == "entry_low":
        entry_target = entry_low
    elif entry_mode == "entry_high":
        entry_target = entry_high
    elif entry_mode == "trigger":
        entry_target = entry_low
    else:
        entry_mode = "entry_mid"
        entry_target = entry_mid

    entry_index = None
    start_i = signal_index + 1
    end_i = min(len(bars_5m) - 1, signal_index + fill_bars)
    for i in range(start_i, end_i + 1):
        b = bars_5m[i]
        if b.low <= entry_target <= b.high:
            entry_index = i
            break

    if entry_index is None:
        return None

    entry_bar = bars_5m[entry_index]
    entry_price = entry_target

    shares = _calc_shares_from_cash(position_cash_cny=position_cash_cny, entry_price=entry_price)
    if shares <= 0:
        return None

    # A-share T+1: cannot sell on the entry day.
    entry_date = entry_bar.ts.date()
    exit_start_i = None
    for i in range(entry_index + 1, len(bars_5m)):
        if bars_5m[i].ts.date() > entry_date:
            exit_start_i = i
            break
    if exit_start_i is None:
        return None

    exit_index = None
    exit_price = None
    outcome = "timeout"
    last_i = min(len(bars_5m) - 1, exit_start_i + hold_bars - 1)
    for i in range(exit_start_i, last_i + 1):
        b = bars_5m[i]
        hit_stop = b.low <= stop_loss
        hit_tp = b.high >= take_profit
        if hit_stop and hit_tp:
            if exit_priority == "tp_first":
                exit_price = take_profit
                outcome = "tp"
            else:
                exit_price = stop_loss
                outcome = "sl"
            exit_index = i
            break
        if hit_stop:
            exit_price = stop_loss
            outcome = "sl"
            exit_index = i
            break
        if hit_tp:
            exit_price = take_profit
            outcome = "tp"
            exit_index = i
            break

    if exit_index is None:
        exit_index = last_i
        exit_price = bars_5m[exit_index].close

    cost_bps = max(0.0, float(fee_bps) + float(slippage_bps))
    if cost_bps > 0:
        entry_price = entry_price * (1 + cost_bps / 10000.0)
        exit_price = exit_price * (1 - cost_bps / 10000.0)

    exit_bar = bars_5m[exit_index]
    entry_notional = float(entry_price) * float(shares)
    exit_notional = float(exit_price) * float(shares)
    total_fees = float(fee_buy_cny) + float(fee_sell_cny)
    net_pnl = (exit_notional - entry_notional) - total_fees
    return_pct = net_pnl / entry_notional if entry_notional > 0 else 0.0
    if cost_bps > 0:
        stop_exec = stop_loss * (1 - cost_bps / 10000.0)
    else:
        stop_exec = stop_loss
    risk = entry_price - stop_exec
    r_multiple = (exit_price - entry_price) / risk if risk > 0 else None

    return TradeResult(
        symbol=symbol,
        signal_time=signal_time,
        entry_time=entry_bar.ts,
        exit_time=exit_bar.ts,
        entry_price=float(entry_price),
        exit_price=float(exit_price),
        return_pct=float(return_pct),
        r_multiple=None if r_multiple is None else float(r_multiple),
        outcome=outcome,
        entry_mode=entry_mode,
        fee_bps=float(fee_bps),
        slippage_bps=float(slippage_bps),
        fee_buy_cny=float(fee_buy_cny),
        fee_sell_cny=float(fee_sell_cny),
        position_cash_cny=float(position_cash_cny),
        shares=int(shares),
        entry_notional_cny=float(entry_notional),
        exit_notional_cny=float(exit_notional),
        net_pnl_cny=float(net_pnl),
        fill_bars=int(fill_bars),
        hold_bars=int(hold_bars),
        tp_level=int(tp_level),
    )


def backtest_breakout_5m(
    *,
    symbol: str,
    bars_5m: list[Bar],
    ind_params: IndicatorParams | None = None,
    params: BreakoutParams | None = None,
    fill_bars: int = 1,
    hold_bars: int = 12,
    tp_level: int = 1,
    exit_priority: str = "stop_first",
    entry_mode: str = "entry_mid",
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    fee_buy_cny: float = 5.0,
    fee_sell_cny: float = 6.0,
    position_cash_cny: float = 10000.0,
) -> BacktestSummary:
    if params is None:
        params = BreakoutParams()
    if ind_params is None:
        ind_params = IndicatorParams()

    signals = breakout_scan_5m(symbol=symbol, bars_5m=bars_5m, ind_params=ind_params, params=params)
    index_by_ts = {b.ts: i for i, b in enumerate(bars_5m)}

    trades: list[TradeResult] = []
    skipped = 0
    for sig in signals:
        sig_index = index_by_ts.get(sig.time)
        if sig_index is None:
            skipped += 1
            continue
        entry_low, entry_high = sig.entry_zone
        entry_mid = (entry_low + entry_high) / 2.0
        tp = sig.take_profit[min(max(tp_level, 1), len(sig.take_profit)) - 1]

        trade = _simulate_trade(
            symbol=sig.symbol,
            bars_5m=bars_5m,
            signal_index=sig_index,
            signal_time=sig.time,
            entry_mid=entry_mid,
            entry_low=entry_low,
            entry_high=entry_high,
            entry_mode=entry_mode,
            stop_loss=sig.stop_loss,
            take_profit=tp,
            fill_bars=fill_bars,
            hold_bars=hold_bars,
            exit_priority=exit_priority,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            fee_buy_cny=fee_buy_cny,
            fee_sell_cny=fee_sell_cny,
            position_cash_cny=position_cash_cny,
            tp_level=tp_level,
        )
        if trade is None:
            skipped += 1
            continue
        trades.append(trade)

    return _summarize(scope=symbol, trades=trades, signals=len(signals), skipped=skipped)


def optimize_breakout_5m(
    *,
    bars_by_symbol: dict[str, list[Bar]],
    lookbacks: list[int],
    vol_factors: list[float],
    metric: str,
    ind_params: IndicatorParams | None = None,
    base_params: BreakoutParams | None = None,
    fill_bars: int = 1,
    hold_bars: int = 12,
    tp_level: int = 1,
    exit_priority: str = "stop_first",
    entry_mode: str = "entry_mid",
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    fee_buy_cny: float = 5.0,
    fee_sell_cny: float = 6.0,
    position_cash_cny: float = 10000.0,
) -> OptimizationResult:
    if ind_params is None:
        ind_params = IndicatorParams()
    if base_params is None:
        base_params = BreakoutParams()

    best_value = -inf
    best_params: dict[str, float | int] = {}
    best_summary = _summarize(scope="ALL", trades=[], signals=0, skipped=0)

    for lb in lookbacks:
        for vf in vol_factors:
            params = replace(base_params, lookback=int(lb), vol_factor=float(vf))
            all_trades: list[TradeResult] = []
            total_signals = 0
            total_skipped = 0
            for sym, bars in bars_by_symbol.items():
                summary = backtest_breakout_5m(
                    symbol=sym,
                    bars_5m=bars,
                    ind_params=ind_params,
                    params=params,
                    fill_bars=fill_bars,
                    hold_bars=hold_bars,
                    tp_level=tp_level,
                    exit_priority=exit_priority,
                    entry_mode=entry_mode,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    fee_buy_cny=fee_buy_cny,
                    fee_sell_cny=fee_sell_cny,
                    position_cash_cny=position_cash_cny,
                )
                all_trades.extend(summary.trades)
                total_signals += summary.signals
                total_skipped += summary.skipped

            summary_all = _summarize(
                scope="ALL",
                trades=all_trades,
                signals=total_signals,
                skipped=total_skipped,
            )

            value = _metric_value(summary_all, metric)
            if value > best_value:
                best_value = value
                best_params = {"lookback": int(lb), "vol_factor": float(vf)}
                best_summary = summary_all

    return OptimizationResult(
        metric=metric,
        best_params=best_params,
        best_value=best_value,
        summary=best_summary,
    )


def _metric_value(summary: BacktestSummary, metric: str) -> float:
    metric = metric.lower().strip()
    if metric == "win_rate":
        return summary.win_rate
    if metric == "profit_factor":
        return float(summary.profit_factor or 0.0)
    if metric == "avg_r":
        return float(summary.avg_r or 0.0)
    return summary.avg_return
