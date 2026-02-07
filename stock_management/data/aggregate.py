from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .models import Bar


def _bucket_start(ts: datetime, anchor_minute: int, freq_minutes: int) -> datetime:
    minutes_from_anchor = (ts.hour * 60 + ts.minute) - anchor_minute
    bucket_index = minutes_from_anchor // freq_minutes
    bucket_start_minute = anchor_minute + bucket_index * freq_minutes
    hour = bucket_start_minute // 60
    minute = bucket_start_minute % 60
    return ts.replace(hour=hour, minute=minute, second=0, microsecond=0)


def aggregate_1m(bars: list[Bar], freq_minutes: int) -> list[Bar]:
    if freq_minutes <= 1:
        return list(bars)

    buckets: dict[datetime, list[Bar]] = defaultdict(list)

    for bar in bars:
        ts = bar.ts.replace(second=0, microsecond=0)
        tmin = ts.hour * 60 + ts.minute

        if 9 * 60 + 30 <= tmin < 11 * 60 + 30:
            anchor = 9 * 60 + 30
        elif 13 * 60 <= tmin < 15 * 60:
            anchor = 13 * 60
        else:
            continue

        key = _bucket_start(ts, anchor, freq_minutes)
        buckets[key].append(bar)

    out: list[Bar] = []
    for key in sorted(buckets.keys()):
        group = sorted(buckets[key], key=lambda b: b.ts)
        first = group[0]
        last = group[-1]
        out.append(
            Bar(
                ts=key,
                open=first.open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=last.close,
                volume=sum(b.volume for b in group),
                amount=(sum((b.amount or 0.0) for b in group) if any(b.amount is not None for b in group) else None),
                source=first.source,
            )
        )
    return out

