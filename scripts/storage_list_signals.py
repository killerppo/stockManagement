from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.storage import SQLiteSignalStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="List recent signals from SQLite store.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "signals.sqlite")
    args = parser.parse_args()

    store = SQLiteSignalStore(args.db)
    rows = store.list_recent(limit=args.limit, symbol=args.symbol)
    print(f"rows={len(rows)} db={args.db}")
    for r in rows:
        print(
            f"- {r.symbol} {r.ts.isoformat()} {r.freq} {r.strategy_id} {r.direction} score={r.score} "
            f"entry=[{r.entry_low:.3f},{r.entry_high:.3f}] stop={r.stop_loss:.3f} tp1={r.tp1:.3f} tp2={r.tp2:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

