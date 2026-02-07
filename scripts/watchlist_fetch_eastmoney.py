from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.data.providers import EastmoneyKlineProvider  # noqa: E402
from stock_management.data.service import DataService  # noqa: E402
from stock_management.watchlist import filter_watchlist, load_watchlist, validate_watchlist  # noqa: E402

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch fetch 1m bars for watchlist (Eastmoney) into SQLite cache.")
    parser.add_argument("--start", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument("--end", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument("--group", default=None, help="Optional group filter (case-insensitive).")
    parser.add_argument("--limit", type=int, default=0, help="If >0, only fetch first N symbols after filtering.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Extra sleep seconds between symbols.")
    parser.add_argument("--watchlist", type=Path, default=REPO_ROOT / "config" / "watchlist.csv")
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    args = parser.parse_args()

    start = _parse_dt(args.start)
    end = _parse_dt(args.end)

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

    provider = EastmoneyKlineProvider()
    service = DataService.with_default_store(provider=provider, data_dir=args.data_dir)

    total_changes = 0
    start_time = time.time()

    for idx, item in enumerate(items, start=1):
        changed = service.ensure_1m(symbol=item.symbol, start=start, end=end)
        total_changes += changed
        print(f"[{idx}/{len(items)}] {item.symbol} upserted_changes={changed}")
        if args.sleep and args.sleep > 0:
            time.sleep(args.sleep)

    elapsed = time.time() - start_time
    print(f"done symbols={len(items)} total_upserted_changes={total_changes} elapsed_sec={elapsed:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

