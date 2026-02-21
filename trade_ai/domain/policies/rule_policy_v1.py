# trade_ai/domain/policies/rule_policy_v1.py
from __future__ import annotations
from typing import Dict
import uuid

from .policy_interface import PolicyInterface
from ..entities.snapshot import SnapshotV3
from ..entities.trade_decision import TradeDecision


class RulePolicyV1(PolicyInterface):
    def __init__(self, rr: float = 2.0, atr_k: float = 1.0):
        self.rr = float(rr)
        self.atr_k = float(atr_k)

    def decide(self, snapshot: SnapshotV3) -> TradeDecision:
        entry_price = float(snapshot.ltf.get("price", {}).get("close"))
        atr_pct = snapshot.ltf.get("price", {}).get("atr_pct") or 0.0
        if atr_pct and atr_pct > 0:
            sl_distance = max(atr_pct * self.atr_k * entry_price, 1e-8)
        else:
            sl_distance = max(0.001 * entry_price, 1e-8)

        htf1 = snapshot.htf.get("1h", {}) or {}
        trend = (htf1.get("trend") or "unknown").lower()
        direction = "LONG" if trend == "up" else "SHORT"

        if direction == "LONG":
            sl_price = entry_price - sl_distance
            tp_price = entry_price + self.rr * sl_distance
            action_type = 1
        else:
            sl_price = entry_price + sl_distance
            tp_price = entry_price - self.rr * sl_distance
            action_type = 0

        risk_unit = abs(entry_price - sl_price)
        return TradeDecision(
            action_type=action_type,
            direction=direction,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            rr=self.rr,
            risk_unit=risk_unit,
            confidence=1.0,
            decision_time_utc=int(snapshot.snapshot_time_utc),
        )
