from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .calendar import expected_minutes, is_session_minute, to_shanghai
from .models import Bar


@dataclass(frozen=True, slots=True)
class QualityIssue:
    kind: str
    message: str
    ts: datetime | None = None


def validate_bars(symbol: str, bars: list[Bar]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if not bars:
        return issues

    last_ts: datetime | None = None
    seen: set[datetime] = set()

    for bar in bars:
        ts = to_shanghai(bar.ts)

        if ts in seen:
            issues.append(QualityIssue("duplicate_ts", f"{symbol} duplicate minute: {ts!s}", ts=ts))
        seen.add(ts)

        if last_ts is not None and ts <= last_ts:
            issues.append(QualityIssue("non_monotonic", f"{symbol} non-increasing ts: {ts!s}", ts=ts))
        last_ts = ts

        if not is_session_minute(ts):
            issues.append(QualityIssue("off_session", f"{symbol} bar outside session: {ts!s}", ts=ts))

        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            issues.append(QualityIssue("non_positive_ohlc", f"{symbol} non-positive OHLC at {ts!s}", ts=ts))

        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close) or bar.high < bar.low:
            issues.append(QualityIssue("ohlc_inconsistent", f"{symbol} inconsistent OHLC at {ts!s}", ts=ts))

        if bar.volume < 0:
            issues.append(QualityIssue("negative_volume", f"{symbol} negative volume at {ts!s}", ts=ts))

    return issues


def find_gaps(symbol: str, bars: list[Bar], start: datetime, end: datetime) -> list[QualityIssue]:
    if not bars:
        return [QualityIssue("missing_all", f"{symbol} no bars in range {start!s} - {end!s}")]

    start = to_shanghai(start)
    end = to_shanghai(end)

    expected = expected_minutes(start, end)
    actual = {to_shanghai(b.ts) for b in bars if start <= to_shanghai(b.ts) < end}
    missing = [m for m in expected if m not in actual]

    return [QualityIssue("missing_minute", f"{symbol} missing minute: {m!s}", ts=m) for m in missing]

