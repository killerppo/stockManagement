from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..models import Bar


def _to_epoch_seconds(ts: datetime) -> int:
    if ts.tzinfo is None:
        raise ValueError("ts must be timezone-aware")
    return int(ts.timestamp())


def _from_epoch_seconds(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


@dataclass(frozen=True, slots=True)
class SQLiteBarStore:
    path: Path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def init(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bars_1m (
                  symbol TEXT NOT NULL,
                  ts INTEGER NOT NULL,
                  open REAL NOT NULL,
                  high REAL NOT NULL,
                  low REAL NOT NULL,
                  close REAL NOT NULL,
                  volume INTEGER NOT NULL,
                  amount REAL,
                  source TEXT NOT NULL,
                  PRIMARY KEY(symbol, ts)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_1m(self, symbol: str, bars: list[Bar]) -> int:
        if not bars:
            return 0
        self.init()

        rows = [
            (
                symbol,
                _to_epoch_seconds(b.ts),
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
                b.amount,
                b.source,
            )
            for b in bars
        ]

        conn = self._connect()
        try:
            conn.executemany(
                """
                INSERT INTO bars_1m(symbol, ts, open, high, low, close, volume, amount, source)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol, ts) DO UPDATE SET
                  open=excluded.open,
                  high=excluded.high,
                  low=excluded.low,
                  close=excluded.close,
                  volume=excluded.volume,
                  amount=excluded.amount,
                  source=excluded.source
                WHERE
                  bars_1m.open   IS NOT excluded.open OR
                  bars_1m.high   IS NOT excluded.high OR
                  bars_1m.low    IS NOT excluded.low OR
                  bars_1m.close  IS NOT excluded.close OR
                  bars_1m.volume IS NOT excluded.volume OR
                  bars_1m.amount IS NOT excluded.amount OR
                  bars_1m.source IS NOT excluded.source
                """,
                rows,
            )
            conn.commit()
            return conn.total_changes
        finally:
            conn.close()

    def load_1m(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        self.init()
        start_epoch = _to_epoch_seconds(start)
        end_epoch = _to_epoch_seconds(end)

        conn = self._connect()
        try:
            cur = conn.execute(
                """
                SELECT ts, open, high, low, close, volume, amount, source
                FROM bars_1m
                WHERE symbol=? AND ts>=? AND ts<?
                ORDER BY ts ASC
                """,
                (symbol, start_epoch, end_epoch),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        out: list[Bar] = []
        for ts_epoch, o, h, l, c, v, amount, source in rows:
            out.append(
                Bar(
                    ts=_from_epoch_seconds(ts_epoch).astimezone(start.tzinfo),
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    volume=int(v),
                    amount=(float(amount) if amount is not None else None),
                    source=str(source),
                )
            )
        return out
