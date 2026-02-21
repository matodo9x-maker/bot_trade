# trade_ai/domain/entities/trade_decision.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import math


class TradeDecisionError(Exception):
    pass


@dataclass(frozen=True)
class TradeDecision:
    action_type: int   # 0=SHORT,1=LONG
    direction: str     # "LONG" or "SHORT"
    entry_price: float
    sl_price: float
    tp_price: float
    rr: float
    risk_unit: float
    confidence: Optional[float]
    decision_time_utc: int

    def __post_init__(self):
        if self.action_type not in (0, 1):
            raise TradeDecisionError("action_type must be 0 or 1")
        expected = "LONG" if self.action_type == 1 else "SHORT"
        if self.direction.upper() != expected:
            raise TradeDecisionError("direction must match action_type")
        if not (self.risk_unit > 0.0):
            raise TradeDecisionError("risk_unit must be > 0")
        calc = abs(self.entry_price - self.sl_price)
        if not math.isclose(calc, self.risk_unit, rel_tol=1e-9, abs_tol=1e-12):
            raise TradeDecisionError("risk_unit must equal abs(entry_price - sl_price)")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise TradeDecisionError("confidence must be between 0 and 1")
        if self.rr is None or self.rr < 0:
            raise TradeDecisionError("rr must be non-negative")
