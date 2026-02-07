from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.watchlist import load_watchlist, validate_watchlist  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate watchlist CSV.")
    parser.add_argument("--watchlist", type=Path, default=REPO_ROOT / "config" / "watchlist.csv")
    args = parser.parse_args()

    items = load_watchlist(args.watchlist)
    issues = validate_watchlist(items)
    print(f"items={len(items)} issues={len(issues)} path={args.watchlist}")
    for i in issues:
        print(f"- {i.kind} {i.symbol or ''} {i.message}")
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())

