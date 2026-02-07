from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.data.service import DataService  # noqa: E402
from stock_management.data.store.sqlite_store import SQLiteBarStore  # noqa: E402
from stock_management.signals import breakout_entry_5m  # noqa: E402

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt


def main() -> int:
    parser = argparse.ArgumentParser(description="Run breakout 5m signal on cached bars and print result.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "bars.sqlite")
    args = parser.parse_args()

    start = _parse_dt(args.start)
    end = _parse_dt(args.end)
    store = SQLiteBarStore(args.db)
    service = DataService(provider=None, store=store)
    bars_5m = service.get_bars(args.symbol, "5m", start, end)
    sig = breakout_entry_5m(symbol=args.symbol, bars_5m=bars_5m)
    if sig is None:
        print("no signal")
        return 0
    print(sig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

