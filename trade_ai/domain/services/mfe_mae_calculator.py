# trade_ai/domain/services/mfe_mae_calculator.py
from __future__ import annotations
from typing import List, Dict


def calculate_mfe_mae_from_ohlc(entry_price: float, direction: str, ohlc_bars: List[Dict]) -> (float, float):
    if not ohlc_bars:
        return 0.0, 0.0

    highs = [b.get("high", entry_price) for b in ohlc_bars]
    lows = [b.get("low", entry_price) for b in ohlc_bars]

    direction = direction.upper()
    if direction == "LONG":
        mfe = max(h - entry_price for h in highs)
        mae = min(l - entry_price for l in lows)
    else:  # SHORT
        mfe = max(entry_price - l for l in lows)
        mae = min(entry_price - h for h in highs)
        mae = -mae

    return float(mfe), float(mae)
