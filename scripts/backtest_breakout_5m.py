from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.backtest import backtest_breakout_5m, optimize_breakout_5m, summarize_trades  # noqa: E402
from stock_management.data.service import DataService  # noqa: E402
from stock_management.data.store.sqlite_store import SQLiteBarStore  # noqa: E402
from stock_management.watchlist import filter_watchlist, load_watchlist  # noqa: E402

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt


def _parse_grid_int(value: str) -> list[int]:
    value = value.strip()
    if ":" in value:
        parts = value.split(":")
        if len(parts) == 3:
            start, stop, step = (int(p) for p in parts)
            if step <= 0:
                raise ValueError("step must be > 0")
            return list(range(start, stop + 1, step))
    return [int(v.strip()) for v in value.split(",") if v.strip()]


def _parse_grid_float(value: str) -> list[float]:
    value = value.strip()
    if ":" in value:
        parts = value.split(":")
        if len(parts) == 3:
            start, stop, step = (float(p) for p in parts)
            if step <= 0:
                raise ValueError("step must be > 0")
            out: list[float] = []
            cur = start
            while cur <= stop + 1e-9:
                out.append(round(cur, 6))
                cur += step
            return out
    return [float(v.strip()) for v in value.split(",") if v.strip()]


def _load_symbols(args) -> list[str]:
    if args.symbol:
        return [args.symbol]
    items = load_watchlist(args.watchlist)
    items = filter_watchlist(items, group=args.group, enabled_only=not args.include_disabled)
    if args.limit is not None:
        items = items[: args.limit]
    return [i.symbol for i in items]


def _print_summary(summary, label: str) -> None:
    pf = summary.profit_factor
    pf_s = "inf" if pf == float("inf") else f"{pf:.3f}" if pf is not None else "na"
    avg_r = f"{summary.avg_r:.3f}" if summary.avg_r is not None else "na"
    avg_win = f"{summary.avg_win:.4f}" if summary.avg_win is not None else "na"
    avg_loss = f"{summary.avg_loss:.4f}" if summary.avg_loss is not None else "na"
    expectancy = f"{summary.expectancy:.4f}" if summary.expectancy is not None else "na"
    print(
        f"{label} trades={len(summary.trades)} wins={summary.wins} "
        f"win_rate={summary.win_rate:.2%} avg_return={summary.avg_return:.4f} "
        f"avg_r={avg_r} avg_win={avg_win} avg_loss={avg_loss} expectancy={expectancy} "
        f"profit_factor={pf_s} max_dd={summary.max_drawdown:.4f} "
        f"signals={summary.signals} skipped={summary.skipped}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest breakout 5m strategy on cached data.")
    parser.add_argument("--symbol", help="e.g. 000001.SZ / 600000.SH")
    parser.add_argument("--watchlist", type=Path, default=REPO_ROOT / "config" / "watchlist.csv")
    parser.add_argument("--group", help="watchlist group filter")
    parser.add_argument("--include-disabled", action="store_true", help="include disabled watchlist items")
    parser.add_argument("--limit", type=int, help="limit symbols from watchlist")
    parser.add_argument("--start", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument("--end", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "bars.sqlite")
    parser.add_argument("--fill-bars", type=int, default=1, help="bars allowed to fill entry mid")
    parser.add_argument("--hold-bars", type=int, default=12, help="bars to hold before timeout")
    parser.add_argument("--tp-level", type=int, default=1, choices=[1, 2], help="use TP1 or TP2")
    parser.add_argument("--exit-priority", default="stop_first", choices=["stop_first", "tp_first"])
    parser.add_argument(
        "--entry-mode",
        default="entry_mid",
        choices=["entry_mid", "entry_low", "entry_high", "trigger"],
        help="entry price mode",
    )
    parser.add_argument("--fee-bps", type=float, default=0.0, help="fee (bps) per side")
    parser.add_argument("--slippage-bps", type=float, default=0.0, help="slippage (bps) per side")
    parser.add_argument("--trades-csv", type=Path, help="write trade details to CSV")

    parser.add_argument("--optimize", action="store_true", help="run parameter grid search")
    parser.add_argument("--metric", default="avg_return", choices=["avg_return", "win_rate", "profit_factor", "avg_r"])
    parser.add_argument("--lookback-grid", default="10,15,20,25,30")
    parser.add_argument("--vol-factor-grid", default="1.2,1.4,1.6,1.8,2.0")
    args = parser.parse_args()

    symbols = _load_symbols(args)
    if not symbols:
        print("no symbols to backtest")
        return 1

    start = _parse_dt(args.start)
    end = _parse_dt(args.end)
    store = SQLiteBarStore(args.db)
    service = DataService(provider=None, store=store)

    bars_by_symbol: dict[str, list] = {}
    for sym in symbols:
        bars = service.get_bars(sym, "5m", start, end)
        if not bars:
            print(f"skip {sym}: no bars")
            continue
        bars_by_symbol[sym] = bars

    if not bars_by_symbol:
        print("no bars loaded")
        return 1

    if args.optimize:
        lookbacks = _parse_grid_int(args.lookback_grid)
        vol_factors = _parse_grid_float(args.vol_factor_grid)
        result = optimize_breakout_5m(
            bars_by_symbol=bars_by_symbol,
            lookbacks=lookbacks,
            vol_factors=vol_factors,
            metric=args.metric,
            fill_bars=args.fill_bars,
            hold_bars=args.hold_bars,
            tp_level=args.tp_level,
            exit_priority=args.exit_priority,
            entry_mode=args.entry_mode,
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
        )
        print(f"best metric={result.metric} value={result.best_value:.4f} params={result.best_params}")
        _print_summary(result.summary, "summary ALL")
        return 0

    all_trades = []
    total_signals = 0
    total_skipped = 0
    for sym, bars in bars_by_symbol.items():
        summary = backtest_breakout_5m(
            symbol=sym,
            bars_5m=bars,
            fill_bars=args.fill_bars,
            hold_bars=args.hold_bars,
            tp_level=args.tp_level,
            exit_priority=args.exit_priority,
            entry_mode=args.entry_mode,
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
        )
        _print_summary(summary, f"summary {sym}")
        all_trades.extend(summary.trades)
        total_signals += summary.signals
        total_skipped += summary.skipped

    summary_all = summarize_trades(scope="ALL", trades=all_trades, signals=total_signals, skipped=total_skipped)
    _print_summary(summary_all, "summary ALL")

    if args.trades_csv:
        import csv

        args.trades_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.trades_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "symbol",
                    "signal_time",
                    "entry_time",
                    "exit_time",
                    "entry_price",
                    "exit_price",
                    "return_pct",
                    "r_multiple",
                    "outcome",
                    "entry_mode",
                    "fee_bps",
                    "slippage_bps",
                    "fill_bars",
                    "hold_bars",
                    "tp_level",
                ]
            )
            for t in all_trades:
                w.writerow(
                    [
                        t.symbol,
                        t.signal_time.isoformat(),
                        t.entry_time.isoformat(),
                        t.exit_time.isoformat(),
                        f"{t.entry_price:.6f}",
                        f"{t.exit_price:.6f}",
                        f"{t.return_pct:.6f}",
                        "" if t.r_multiple is None else f"{t.r_multiple:.6f}",
                        t.outcome,
                        t.entry_mode,
                        f"{t.fee_bps:.4f}",
                        f"{t.slippage_bps:.4f}",
                        t.fill_bars,
                        t.hold_bars,
                        t.tp_level,
                    ]
                )
        print(f"trades_csv={args.trades_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
