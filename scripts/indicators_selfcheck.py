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
from stock_management.indicators import IndicatorParams, compute_all  # noqa: E402

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute indicators from cached bars and print latest values.")
    parser.add_argument("--symbol", required=True, help="e.g. 000001.SZ / 600000.SH")
    parser.add_argument("--freq", choices=["1m", "5m", "15m", "60m"], default="5m")
    parser.add_argument("--start", required=True, help="ISO datetime")
    parser.add_argument("--end", required=True, help="ISO datetime")
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "bars.sqlite")
    args = parser.parse_args()

    start = _parse_dt(args.start)
    end = _parse_dt(args.end)
    store = SQLiteBarStore(args.db)
    service = DataService(provider=None, store=store)
    bars = service.get_bars(args.symbol, args.freq, start, end)
    if not bars:
        print("no bars")
        return 2

    params = IndicatorParams()
    ind = compute_all(bars, params)
    last_idx = len(bars) - 1
    print(f"bars={len(bars)} last_ts={bars[last_idx].ts.isoformat()} freq={args.freq}")
    for k in sorted(ind.keys()):
        v = ind[k][last_idx]
        if v is None:
            continue
        print(f"- {k}={v:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
