from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.data.providers.csv_provider import CsvProvider  # noqa: E402
from stock_management.data.quality import find_gaps, validate_bars  # noqa: E402
from stock_management.data.service import DataService  # noqa: E402
from stock_management.data.store.sqlite_store import SQLiteBarStore  # noqa: E402

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E smoketest: CSV -> import -> read -> aggregate.")
    parser.add_argument("--csv-dir", type=Path, default=REPO_ROOT / "examples" / "csv")
    parser.add_argument("--symbol", default="000001.SZ")
    parser.add_argument("--start", default="2026-02-06T09:30:00+08:00")
    parser.add_argument("--end", default="2026-02-06T09:50:00+08:00")
    args = parser.parse_args()

    start = _parse_dt(args.start)
    end = _parse_dt(args.end)

    provider = CsvProvider(root_dir=args.csv_dir)
    bars = provider.fetch_1m_bars(symbol=args.symbol, start=start, end=end)
    if not bars:
        print("FAIL: no bars loaded from CSV")
        return 2

    issues = validate_bars(args.symbol, bars)
    gaps = find_gaps(args.symbol, bars, start=start, end=end)
    if issues:
        print(f"FAIL: validate_bars issues={len(issues)} (showing up to 10)")
        for i in issues[:10]:
            print(f"- {i.kind} {i.ts.isoformat() if i.ts else ''} {i.message}")
        return 2
    if gaps:
        print(f"FAIL: gaps={len(gaps)} (showing up to 10)")
        for g in gaps[:10]:
            print(f"- {g.kind} {g.ts.isoformat() if g.ts else ''} {g.message}")
        return 2

    with tempfile.TemporaryDirectory(prefix="stockManagement_data_e2e_") as tmp:
        data_dir = Path(tmp)

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "data_import_csv.py"),
            "--csv-dir",
            str(args.csv_dir),
            "--symbol",
            args.symbol,
            "--start",
            start.isoformat(),
            "--end",
            end.isoformat(),
            "--data-dir",
            str(data_dir),
        ]
        r = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print("FAIL: data_import_csv.py failed")
            print(r.stdout)
            print(r.stderr)
            return 2

        store = SQLiteBarStore(path=data_dir / "bars.sqlite")
        loaded = store.load_1m(symbol=args.symbol, start=start, end=end)

        if len(loaded) != len(bars):
            print(f"FAIL: loaded bars mismatch: csv={len(bars)} sqlite={len(loaded)}")
            return 2

        service = DataService(provider=provider, store=store)
        bars_5m = service.get_bars(symbol=args.symbol, freq="5m", start=start, end=end)
        bars_15m = service.get_bars(symbol=args.symbol, freq="15m", start=start, end=end)

        print(
            "PASS:",
            f"bars_1m={len(loaded)}",
            f"bars_5m={len(bars_5m)}",
            f"bars_15m={len(bars_15m)}",
        )
        print("sample_5m_first:", bars_5m[0])
        print("sample_5m_last:", bars_5m[-1])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

