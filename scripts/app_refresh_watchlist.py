from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.data.calendar import TZ_SHANGHAI, is_session_minute  # noqa: E402
from stock_management.data.providers import EastmoneyKlineProvider, TushareProProvider  # noqa: E402
from stock_management.data.service import DataService  # noqa: E402
from stock_management.signals import breakout_entry_5m  # noqa: E402
from stock_management.indicators import IndicatorParams  # noqa: E402
from stock_management.signals.params import BreakoutParams  # noqa: E402
from stock_management.storage import SQLiteSignalStore  # noqa: E402
from stock_management.watchlist import filter_watchlist, load_watchlist, validate_watchlist  # noqa: E402


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt


def _now_minute() -> datetime:
    return datetime.now(tz=TZ_SHANGHAI).replace(second=0, microsecond=0)


def _build_provider(name: str):
    if name == "eastmoney":
        return EastmoneyKlineProvider()
    if name == "tushare":
        return TushareProProvider.from_env()
    raise ValueError(f"unsupported provider: {name}")


def _run_once(
    *,
    service: DataService,
    symbols: list[str],
    start: datetime,
    end: datetime,
    sleep_sec: float,
    run_signals: bool,
    signal_window_minutes: int,
    signal_store: SQLiteSignalStore | None,
) -> int:
    total_changes = 0
    failed: list[tuple[str, str]] = []
    signals: list[object] = []
    signals_to_store = []

    for idx, symbol in enumerate(symbols, start=1):
        try:
            changed = service.ensure_1m(symbol=symbol, start=start, end=end)
            total_changes += changed
            print(f"[{idx}/{len(symbols)}] {symbol} upserted_changes={changed}")

            if run_signals:
                sig_start = end - timedelta(minutes=max(signal_window_minutes, 1))
                bars_5m = service.get_bars(symbol, "5m", sig_start, end)
                sig = breakout_entry_5m(symbol=symbol, bars_5m=bars_5m)
                if sig is not None:
                    signals.append(sig)
                    signals_to_store.append(sig)
        except Exception as e:  # noqa: BLE001
            failed.append((symbol, str(e)))
            print(f"[{idx}/{len(symbols)}] {symbol} ERROR {e}")

        if sleep_sec > 0:
            time.sleep(sleep_sec)

    print(f"summary symbols={len(symbols)} total_upserted_changes={total_changes} signals={len(signals)} failed={len(failed)}")
    if signals:
        print("signals:")
        for s in signals[:20]:
            print(f"- {s}")
    if signal_store is not None and signals_to_store:
        ind_params = IndicatorParams()
        strat_params = BreakoutParams()
        inserted = signal_store.insert_signals(
            signals_to_store,
            strategy_id="breakout_5m_v1",
            params_snapshot={
                "indicator_params": ind_params.__dict__,
                "strategy_params": strat_params.__dict__,
            },
        )
        print(f"signals_stored={inserted} db={signal_store.path}")
    if failed:
        for symbol, msg in failed[:10]:
            print(f"- failed {symbol} {msg}")
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="App entry: refresh watchlist minute bars into local cache.")
    parser.add_argument("--provider", choices=["eastmoney", "tushare"], default="eastmoney")
    parser.add_argument("--watchlist", type=Path, default=REPO_ROOT / "config" / "watchlist.csv")
    parser.add_argument("--group", default=None, help="Optional group filter (case-insensitive).")
    parser.add_argument("--limit", type=int, default=0, help="If >0, only refresh first N symbols after filtering.")

    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--window-minutes", type=int, default=60, help="Rolling window length when start/end not set.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Extra sleep seconds between symbols.")

    parser.add_argument("--signals", action="store_true", help="Run signals after refresh (breakout 5m).")
    parser.add_argument(
        "--signal-window-minutes",
        type=int,
        default=240,
        help="Lookback window for signal computation (default: 240).",
    )
    parser.add_argument("--log-signals", action="store_true", help="Persist emitted signals into SQLite store.")
    parser.add_argument(
        "--signals-db",
        type=Path,
        default=REPO_ROOT / "data" / "signals.sqlite",
        help="Signals SQLite path (default: <repo>/data/signals.sqlite).",
    )

    parser.add_argument("--start", default=None, help="ISO datetime. If set, run once for this window.")
    parser.add_argument("--end", default=None, help="ISO datetime. If set, run once for this window.")

    parser.add_argument("--loop", action="store_true", help="Loop refresh every --interval seconds.")
    parser.add_argument("--interval", type=int, default=60, help="Loop interval seconds (default: 60).")
    parser.add_argument("--run-off-session", action="store_true", help="Allow running outside trading session.")
    args = parser.parse_args()

    items = load_watchlist(args.watchlist)
    issues = validate_watchlist(items)
    if issues:
        print(f"watchlist invalid: issues={len(issues)} path={args.watchlist}")
        for i in issues:
            print(f"- {i.kind} {i.symbol or ''} {i.message}")
        return 2

    items = filter_watchlist(items, group=args.group, enabled_only=True)
    if args.limit and args.limit > 0:
        items = items[: args.limit]
    symbols = [i.symbol for i in items]
    if not symbols:
        print("no symbols to refresh")
        return 0

    provider = _build_provider(args.provider)
    service = DataService.with_default_store(provider=provider, data_dir=args.data_dir)
    signal_store = SQLiteSignalStore(args.signals_db) if args.log_signals else None

    fixed_start = _parse_dt(args.start) if args.start else None
    fixed_end = _parse_dt(args.end) if args.end else None
    if (fixed_start is None) != (fixed_end is None):
        raise ValueError("start and end must be set together")

    def compute_window() -> tuple[datetime, datetime]:
        if fixed_start and fixed_end:
            return fixed_start, fixed_end
        end = _now_minute()
        start = end - timedelta(minutes=max(args.window_minutes, 1))
        return start, end

    while True:
        start, end = compute_window()
        if not args.run_off_session and not is_session_minute(end - timedelta(minutes=1)):
            print(f"skip off-session now={_now_minute().isoformat()}")
        else:
            print(f"refresh provider={args.provider} start={start.isoformat()} end={end.isoformat()} symbols={len(symbols)}")
            rc = _run_once(
                service=service,
                symbols=symbols,
                start=start,
                end=end,
                sleep_sec=args.sleep,
                run_signals=args.signals,
                signal_window_minutes=args.signal_window_minutes,
                signal_store=signal_store,
            )
            if rc != 0 and not args.loop:
                return rc

        if not args.loop or (fixed_start and fixed_end):
            return 0
        time.sleep(max(args.interval, 1))


if __name__ == "__main__":
    raise SystemExit(main())
