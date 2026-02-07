from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WatchItem:
    symbol: str
    group: str | None = None
    enabled: bool = True
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Issue:
    kind: str
    message: str
    symbol: str | None = None

