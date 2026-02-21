# trade_ai/application/ports/market_data_port.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Dict


class MarketDataPort(ABC):
    @abstractmethod
    def get_ohlc(self, symbol: str, start_ts: int, end_ts: int, timeframe: str) -> List[Dict]:
        raise NotImplementedError()
