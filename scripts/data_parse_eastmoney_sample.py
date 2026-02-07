from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stock_management.data.providers.eastmoney_provider import _parse_kline_row  # noqa: E402


def main() -> int:
    path = REPO_ROOT / "examples" / "eastmoney" / "kline_1m.sample.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    klines = payload["data"]["klines"]
    bars = [_parse_kline_row(row, source="eastmoney_sample") for row in klines]
    print(f"bars={len(bars)} first_ts={bars[0].ts.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

