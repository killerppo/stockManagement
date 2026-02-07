from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import Issue, WatchItem


_SYMBOL_RE = re.compile(r"^\d{6}\.(SZ|SH)$", re.IGNORECASE)


def _parse_enabled(value: str | None) -> bool:
    if value is None:
        return True
    v = value.strip()
    if v == "":
        return True
    if v in ("1", "true", "TRUE", "True", "yes", "YES", "Yes", "y", "Y"):
        return True
    if v in ("0", "false", "FALSE", "False", "no", "NO", "No", "n", "N"):
        return False
    return True


def load_watchlist(path: Path) -> list[WatchItem]:
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8", newline="") as f:
        lines = [line for line in f]

    # Header must be the first non-empty, non-comment line.
    header_idx = None
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        header_idx = i
        break
    if header_idx is None:
        return []

    header_line = lines[header_idx]
    data_lines = [
        line
        for line in lines[header_idx + 1 :]
        if line.strip() and not line.lstrip().startswith("#")
    ]

    rows: list[dict[str, str]] = []
    reader = csv.DictReader([header_line, *data_lines])
    for row in reader:
        rows.append({k: (v or "").strip() for k, v in row.items() if k is not None})

    items: list[WatchItem] = []
    for row in rows:
        symbol = row.get("symbol", "").strip().upper()
        group = (row.get("group") or "").strip() or None
        enabled = _parse_enabled(row.get("enabled"))
        note = (row.get("note") or "").strip() or None
        if not symbol:
            continue
        items.append(WatchItem(symbol=symbol, group=group, enabled=enabled, note=note))
    return items


def validate_watchlist(items: list[WatchItem]) -> list[Issue]:
    issues: list[Issue] = []
    seen: set[str] = set()

    for item in items:
        symbol = item.symbol.upper()
        if not _SYMBOL_RE.match(symbol):
            issues.append(Issue("bad_symbol", f"invalid symbol format: {item.symbol}", symbol=item.symbol))
            continue
        if symbol in seen:
            issues.append(Issue("duplicate_symbol", f"duplicate symbol: {symbol}", symbol=symbol))
        seen.add(symbol)

    return issues


def filter_watchlist(
    items: list[WatchItem],
    group: str | None = None,
    enabled_only: bool = True,
) -> list[WatchItem]:
    out: list[WatchItem] = []
    for item in items:
        if enabled_only and not item.enabled:
            continue
        if group is not None and (item.group or "").lower() != group.lower():
            continue
        out.append(item)
    return out
