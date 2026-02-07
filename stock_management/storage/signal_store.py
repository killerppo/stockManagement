from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from stock_management.signals.models import Signal


def _to_epoch_seconds(ts: datetime) -> int:
    if ts.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return int(ts.astimezone(timezone.utc).timestamp())


def _now_epoch() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


@dataclass(frozen=True, slots=True)
class SignalRow:
    id: int
    symbol: str
    ts: datetime
    freq: str
    strategy_id: str
    direction: str
    score: int
    entry_low: float
    entry_high: float
    stop_loss: float
    tp1: float
    tp2: float
    reasons: list[dict]
    risk_flags: list[str]
    params: dict
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SQLiteSignalStore:
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
                CREATE TABLE IF NOT EXISTS signals (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  symbol TEXT NOT NULL,
                  ts INTEGER NOT NULL,
                  freq TEXT NOT NULL,
                  strategy_id TEXT NOT NULL,
                  direction TEXT NOT NULL,
                  score INTEGER NOT NULL,
                  entry_low REAL NOT NULL,
                  entry_high REAL NOT NULL,
                  stop_loss REAL NOT NULL,
                  tp1 REAL NOT NULL,
                  tp2 REAL NOT NULL,
                  reasons_json TEXT NOT NULL,
                  risk_flags_json TEXT NOT NULL,
                  params_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  UNIQUE(symbol, ts, freq, strategy_id)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def insert_signals(
        self,
        signals: list[Signal],
        *,
        strategy_id: str,
        params_snapshot: dict,
    ) -> int:
        if not signals:
            return 0
        self.init()

        created_at = _now_epoch()
        rows = []
        for s in signals:
            reasons = [asdict(r) for r in s.reasons]
            rows.append(
                (
                    s.symbol,
                    _to_epoch_seconds(s.time),
                    s.freq,
                    strategy_id,
                    s.direction,
                    int(s.score),
                    float(s.entry_zone[0]),
                    float(s.entry_zone[1]),
                    float(s.stop_loss),
                    float(s.take_profit[0]),
                    float(s.take_profit[1]),
                    json.dumps(reasons, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(list(s.risk_flags), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(params_snapshot, ensure_ascii=False, separators=(",", ":")),
                    created_at,
                )
            )

        conn = self._connect()
        try:
            conn.executemany(
                """
                INSERT OR IGNORE INTO signals(
                  symbol, ts, freq, strategy_id, direction, score,
                  entry_low, entry_high, stop_loss, tp1, tp2,
                  reasons_json, risk_flags_json, params_json, created_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
            conn.commit()
            return conn.total_changes
        finally:
            conn.close()

    def list_recent(self, *, limit: int = 50, symbol: str | None = None) -> list[SignalRow]:
        self.init()
        lim = max(1, min(500, int(limit)))
        conn = self._connect()
        try:
            if symbol:
                cur = conn.execute(
                    """
                    SELECT id, symbol, ts, freq, strategy_id, direction, score,
                           entry_low, entry_high, stop_loss, tp1, tp2,
                           reasons_json, risk_flags_json, params_json, created_at
                    FROM signals
                    WHERE symbol=?
                    ORDER BY ts DESC, id DESC
                    LIMIT ?
                    """,
                    (symbol, lim),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, symbol, ts, freq, strategy_id, direction, score,
                           entry_low, entry_high, stop_loss, tp1, tp2,
                           reasons_json, risk_flags_json, params_json, created_at
                    FROM signals
                    ORDER BY ts DESC, id DESC
                    LIMIT ?
                    """,
                    (lim,),
                )
            rows = cur.fetchall()
        finally:
            conn.close()

        out: list[SignalRow] = []
        for (
            id_,
            sym,
            ts_epoch,
            freq,
            strategy_id,
            direction,
            score,
            entry_low,
            entry_high,
            stop_loss,
            tp1,
            tp2,
            reasons_json,
            risk_flags_json,
            params_json,
            created_at_epoch,
        ) in rows:
            out.append(
                SignalRow(
                    id=int(id_),
                    symbol=str(sym),
                    ts=datetime.fromtimestamp(int(ts_epoch), tz=timezone.utc),
                    freq=str(freq),
                    strategy_id=str(strategy_id),
                    direction=str(direction),
                    score=int(score),
                    entry_low=float(entry_low),
                    entry_high=float(entry_high),
                    stop_loss=float(stop_loss),
                    tp1=float(tp1),
                    tp2=float(tp2),
                    reasons=list(json.loads(str(reasons_json))),
                    risk_flags=list(json.loads(str(risk_flags_json))),
                    params=dict(json.loads(str(params_json))),
                    created_at=datetime.fromtimestamp(int(created_at_epoch), tz=timezone.utc),
                )
            )
        return out

