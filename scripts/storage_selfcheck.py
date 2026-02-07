from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.signals.models import Reason, Signal  # noqa: E402
from stock_management.storage import SQLiteSignalStore  # noqa: E402

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def main() -> int:
    parser = argparse.ArgumentParser(description="Storage selfcheck: insert a dummy signal and list recent rows.")
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "signals.sqlite")
    args = parser.parse_args()

    store = SQLiteSignalStore(args.db)
    sig = Signal(
        symbol="000001.SZ",
        time=datetime(2026, 2, 6, 10, 0, tzinfo=TZ_SHANGHAI),
        freq="5m",
        direction="Entry",
        score=70,
        entry_zone=(10.0, 10.02),
        stop_loss=9.9,
        take_profit=(10.12, 10.24),
        reasons=(Reason("dummy", current=1.0, threshold=0.0, passed=True),),
        risk_flags=(),
    )
    inserted = store.insert_signals([sig], strategy_id="selfcheck", params_snapshot={"note": "selfcheck"})
    rows = store.list_recent(limit=5, symbol="000001.SZ")
    print(f"inserted={inserted} recent_rows={len(rows)} db={args.db}")
    for r in rows:
        print(f"- id={r.id} ts={r.ts.isoformat()} strategy={r.strategy_id} score={r.score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

