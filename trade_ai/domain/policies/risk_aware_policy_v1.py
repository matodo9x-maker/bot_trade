# trade_ai/domain/policies/risk_aware_policy_v1.py
from __future__ import annotations
from typing import Dict, Any
import math
import uuid

from .policy_interface import PolicyInterface
from ..entities.snapshot import SnapshotV3
from ..entities.trade_decision import TradeDecision

class RiskAwarePolicyV1(PolicyInterface):
    """
    Risk-aware rule policy that computes RR (rr) dynamically from snapshot.
    - Uses volatility_regime (ltf.price.volatility_regime) to pick a base RR
    - Modulates RR using atr_pct and optional funding_zscore / liquidity signals
    - Computes sl_distance from atr_pct * atr_k * entry_price (fallback floor)
    - Ensures rr in [rr_floor, rr_ceiling]
    - Deterministic given same snapshot and config
    """

    DEFAULT_VOL_RR = {"dead": 1.0, "normal": 2.0, "expansion": 3.0}
    VOL_SCORE = {"dead": 0.8, "normal": 1.0, "expansion": 1.2}

    def __init__(
        self,
        rr_map: Dict[str, float] = None,
        atr_k: float = 1.0,
        rr_floor: float = 0.5,
        rr_ceiling: float = 10.0,
        vol_weight: float = 1.0,
        atr_weight: float = 1.0,
        funding_weight: float = 0.5,
    ):
        self.rr_map = rr_map or dict(self.DEFAULT_VOL_RR)
        self.atr_k = float(atr_k)
        self.rr_floor = float(rr_floor)
        self.rr_ceiling = float(rr_ceiling)
        self.vol_weight = float(vol_weight)
        self.atr_weight = float(atr_weight)
        self.funding_weight = float(funding_weight)

    @staticmethod
    def _safe_get(d: Dict[str, Any], path: str, default=None):
        parts = path.split(".")
        cur = d
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur

    def _compute_rr(self, snapshot: SnapshotV3) -> float:
        # base RR from volatility regime (ltf)
        vol_regime = self._safe_get(snapshot.to_dict(), "ltf.price.volatility_regime", None)
        base_rr = float(self.rr_map.get(vol_regime, self.rr_map.get("normal", 2.0)))

        # atr_pct (e.g., 0.005 for 0.5%)
        atr_pct = self._safe_get(snapshot.to_dict(), "ltf.price.atr_pct", 0.0) or 0.0
        # strength of volatility: higher atr_pct -> more volatile -> we scale RR moderately
        # normalize atr_pct into a small scalar: atr_pct_pct = atr_pct * 100 (percent)
        atr_term = 1.0 + self.atr_weight * (atr_pct * 100.0)

        # funding_zscore adjusts aggressiveness: positive funding (longs paying shorts) -> reduce rr
        funding_z = self._safe_get(snapshot.to_dict(), "context.funding_zscore", 0.0) or 0.0
        funding_adj = 1.0 - (self.funding_weight * float(funding_z))

        # Compose
        rr = base_rr * (1.0 * self.vol_weight) * atr_term * funding_adj

        # clamp
        rr = max(self.rr_floor, min(self.rr_ceiling, float(rr)))
        return float(rr)

    def decide(self, snapshot: SnapshotV3) -> TradeDecision:
        data = snapshot.to_dict()
        entry_price = float(self._safe_get(data, "ltf.price.close", 0.0))
        if entry_price == 0.0:
            # safe fallback
            entry_price = 1.0

        atr_pct = float(self._safe_get(data, "ltf.price.atr_pct", 0.0) or 0.0)

        # compute sl distance
        if atr_pct and atr_pct > 0:
            sl_distance = max(self.atr_k * atr_pct * entry_price, 1e-8)
        else:
            sl_distance = max(0.001 * entry_price, 1e-8)

        # compute rr dynamically
        rr = self._compute_rr(snapshot)

        # direction decision (example: use 1h trend)
        htf1 = data.get("htf", {}).get("1h", {}) or {}
        trend = (htf1.get("trend") or "unknown").lower()
        direction = "LONG" if trend == "up" else "SHORT"
        action_type = 1 if direction == "LONG" else 0

        if direction == "LONG":
            sl_price = entry_price - sl_distance
            tp_price = entry_price + rr * sl_distance
        else:
            sl_price = entry_price + sl_distance
            tp_price = entry_price - rr * sl_distance

        risk_unit = abs(entry_price - sl_price)
        # ensure risk_unit > 0
        if not (risk_unit > 0.0):
            risk_unit = max(1e-8, abs(entry_price) * 1e-6)

        return TradeDecision(
            action_type=action_type,
            direction=direction,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            rr=rr,
            risk_unit=risk_unit,
            confidence=1.0,
            decision_time_utc=int(snapshot.snapshot_time_utc),
        )
