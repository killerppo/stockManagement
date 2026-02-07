from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.data.quality import find_gaps  # noqa: E402
from stock_management.data.store.sqlite_store import SQLiteBarStore  # noqa: E402

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect cached 1m bars in SQLite and report gaps.")
    parser.add_argument("--symbol", required=True, help="e.g. 000001.SZ / 600000.SH")
    parser.add_argument("--start", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument("--end", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument(
        "--db",
        type=Path,
        default=REPO_ROOT / "data" / "bars.sqlite",
        help="SQLite path (default: <repo>/data/bars.sqlite).",
    )
    args = parser.parse_args()

    start = _parse_dt(args.start)
    end = _parse_dt(args.end)
    store = SQLiteBarStore(args.db)
    bars = store.load_1m(args.symbol, start, end)
    gaps = find_gaps(args.symbol, bars, start, end)

    first = bars[0].ts.isoformat() if bars else None
    last = bars[-1].ts.isoformat() if bars else None
    print(f"bars_1m={len(bars)} gaps={len(gaps)} first={first} last={last} db={args.db}")
    for g in gaps[:10]:
        print(f"- {g.kind} {g.ts.isoformat() if g.ts else ''} {g.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

