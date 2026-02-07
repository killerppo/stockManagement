from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Bar


class DataProvider(ABC):
    provider_id: str = "unknown"
    volume_unit: str = "unknown"

    @abstractmethod
    def fetch_1m_bars(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        raise NotImplementedError
