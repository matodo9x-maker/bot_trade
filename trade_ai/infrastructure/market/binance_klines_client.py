# trade_ai/infrastructure/market/binance_klines_client.py
from __future__ import annotations
from typing import List, Dict
import time


class BinanceKlinesClient:
    """
    Lightweight stub: in production replace with real Binance/CCXT client.
    For now returns synthetic OHLC or can wrap a CSV loader.
    """
    def __init__(self):
        pass

    def get_ohlc(self, symbol: str, start_ts: int, end_ts: int, timeframe: str) -> List[Dict]:
        # Return empty list or synthetic candles.
        # Production: query exchange/candles.
        return []
