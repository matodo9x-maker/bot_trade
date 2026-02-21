# trade_ai/domain/entities/reward_state.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class RewardState:
    pnl_raw: float
    pnl_r: float
    mfe: float
    mae: float
    holding_seconds: int
    reward_version: str = "v1"

    # Optional (futures): realized values in USDT, keeping backward compatibility.
    pnl_usdt: Optional[float] = None
    risk_usdt: Optional[float] = None
    qty: Optional[float] = None
    fees_usdt: Optional[float] = None
    funding_usdt: Optional[float] = None
