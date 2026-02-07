from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.data.providers.csv_provider import CsvProvider
from stock_management.data.service import DataService


TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import 1m bars from CSV into local SQLite store.")
    parser.add_argument("--csv-dir", type=Path, required=True, help="Directory containing <symbol>.csv files.")
    parser.add_argument("--symbol", required=True, help="Symbol filename prefix, e.g. 000001.SZ")
    parser.add_argument("--start", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument("--end", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data",
        help="Local data directory (default: <repo>/data).",
    )
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    if start.tzinfo is None:
        start = start.replace(tzinfo=TZ_SHANGHAI)
    if end.tzinfo is None:
        end = end.replace(tzinfo=TZ_SHANGHAI)

    provider = CsvProvider(root_dir=args.csv_dir)
    service = DataService.with_default_store(provider=provider, data_dir=args.data_dir)
    changed = service.refresh_1m(symbol=args.symbol, start=start, end=end)
    print(f"upserted_changes={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
