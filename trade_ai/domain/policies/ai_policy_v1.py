# trade_ai/domain/policies/ai_policy_v1.py
from __future__ import annotations
from typing import Dict, Any
import numpy as np

from .policy_interface import PolicyInterface
from ..entities.snapshot import SnapshotV3
from ..entities.trade_decision import TradeDecision

class AIPolicyV1(PolicyInterface):
    """
    Skeleton: loads a model artifact (left as stub). Should:
    - call feature_mapper to get vector
    - run model -> logits/probabilities
    - map to action_type, rr/confidence
    - return TradeDecision
    """
    def __init__(self, model_path: str, feature_mapper):
        # model loading stub: in production replace with real model loader
        self.model_path = model_path
        self.feature_mapper = feature_mapper

    def decide(self, snapshot: SnapshotV3) -> TradeDecision:
        # Feature vector
        fv = self.feature_mapper.map(snapshot.to_dict()).features
        # fake model inference (stub)
        # For now: choose LONG if mean > 0 else SHORT
        mean = float(np.mean(fv))
        action_type = 1 if mean >= 0 else 0
        direction = "LONG" if action_type == 1 else "SHORT"
        entry_price = float(snapshot.ltf.get("price", {}).get("close"))
        # simplistic rr: based on variance
        rr = float(max(1.0, min(5.0, np.std(fv) * 10 + 1.0)))
        # choose sl distance small fraction of price for demo
        sl_distance = max(1e-8, 0.001 * entry_price)
        if direction == "LONG":
            sl_price = entry_price - sl_distance
            tp_price = entry_price + rr * sl_distance
        else:
            sl_price = entry_price + sl_distance
            tp_price = entry_price - rr * sl_distance

        risk_unit = abs(entry_price - sl_price)
        return TradeDecision(
            action_type=action_type,
            direction=direction,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            rr=rr,
            risk_unit=risk_unit,
            confidence=0.9,
            decision_time_utc=int(snapshot.snapshot_time_utc),
        )
