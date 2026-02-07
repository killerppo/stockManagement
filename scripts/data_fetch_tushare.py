from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.data.providers.tushare_provider import TushareProProvider  # noqa: E402
from stock_management.data.service import DataService  # noqa: E402

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch 1m bars from Tushare and cache into local SQLite store.")
    parser.add_argument("--symbol", required=True, help="e.g. 000001.SZ")
    parser.add_argument("--start", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument("--end", required=True, help="ISO datetime, tz-aware preferred (Asia/Shanghai).")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data",
        help="Local data directory (default: <repo>/data).",
    )
    args = parser.parse_args()

    provider = TushareProProvider.from_env()
    service = DataService.with_default_store(provider=provider, data_dir=args.data_dir)

    start = _parse_dt(args.start)
    end = _parse_dt(args.end)
    changed = service.ensure_1m(symbol=args.symbol, start=start, end=end)
    print(f"upserted_changes={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
