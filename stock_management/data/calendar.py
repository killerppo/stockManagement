from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class TradingSession:
    start: time
    end: time  # exclusive


SESSIONS = (
    TradingSession(start=time(9, 30), end=time(11, 30)),
    TradingSession(start=time(13, 0), end=time(15, 0)),
)


def to_shanghai(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (Asia/Shanghai)")
    return dt.astimezone(TZ_SHANGHAI)


def is_session_minute(dt: datetime) -> bool:
    dt = to_shanghai(dt)
    t = dt.timetz().replace(tzinfo=None)
    for session in SESSIONS:
        if session.start <= t < session.end:
            return True
    return False


def iter_session_minutes(trading_day: date) -> list[datetime]:
    if trading_day.weekday() >= 5:
        return []
    minutes: list[datetime] = []
    for session in SESSIONS:
        start_dt = datetime.combine(trading_day, session.start, TZ_SHANGHAI)
        end_dt = datetime.combine(trading_day, session.end, TZ_SHANGHAI)
        cursor = start_dt
        while cursor < end_dt:
            minutes.append(cursor)
            cursor += timedelta(minutes=1)
    return minutes


def expected_minutes(start: datetime, end: datetime) -> list[datetime]:
    start = to_shanghai(start)
    end = to_shanghai(end)
    if end <= start:
        return []

    minutes: list[datetime] = []
    cursor_day = start.date()
    while cursor_day <= end.date():
        for minute in iter_session_minutes(cursor_day):
            if start <= minute < end:
                minutes.append(minute)
        cursor_day = cursor_day + timedelta(days=1)
    return minutes
