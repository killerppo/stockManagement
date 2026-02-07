from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.data.aggregate import aggregate_1m
from stock_management.data.providers.csv_provider import CsvProvider
from stock_management.data.quality import find_gaps, validate_bars


TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def main() -> int:
    parser = argparse.ArgumentParser(description="Self-check CSV bars: validate + gap check + aggregate.")
    parser.add_argument("--csv-dir", type=Path, required=True, help="Directory containing <symbol>.csv files.")
    parser.add_argument("--symbol", required=True, help="Symbol filename prefix, e.g. 000001.SZ")
    parser.add_argument("--start", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument("--end", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument("--agg", type=int, default=5, help="Aggregate minutes (default: 5).")
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    if start.tzinfo is None:
        start = start.replace(tzinfo=TZ_SHANGHAI)
    if end.tzinfo is None:
        end = end.replace(tzinfo=TZ_SHANGHAI)

    provider = CsvProvider(root_dir=args.csv_dir)
    bars = provider.fetch_1m_bars(symbol=args.symbol, start=start, end=end)

    issues = validate_bars(args.symbol, bars)
    gaps = find_gaps(args.symbol, bars, start=start, end=end)
    agg = aggregate_1m(bars, args.agg)

    print(f"bars_1m={len(bars)} issues={len(issues)} gaps={len(gaps)} bars_{args.agg}m={len(agg)}")
    for issue in (issues[:10] + gaps[:10]):
        ts = issue.ts.isoformat() if issue.ts else ""
        print(f"- {issue.kind} {ts} {issue.message}")

    if issues:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
