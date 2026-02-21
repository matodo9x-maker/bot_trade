# trade_ai/domain/policies/hybrid_policy_v1.py
from __future__ import annotations

from typing import Optional

from .policy_interface import PolicyInterface
from ..entities.snapshot import SnapshotV3
from ..entities.trade_decision import TradeDecision
from ..services.model_scorer_v1 import ModelScorerV1
from ...feature_engineering.feature_mapper_v1 import FeatureMapperV1


class HybridPolicyV1(PolicyInterface):
    """Hybrid: Rule-based decision (RR/SL/TP) + ML scorer (XGB/LGBM) as confidence.

    - The *rule policy* determines direction and price levels.
    - The *model scorer* outputs a probability-like score in [0,1].
    - This score is written into TradeDecision.confidence.

    IMPORTANT: This policy does NOT decide "no trade".
    Use RiskEngineV1.min_confidence (or your own gate) to skip low-score signals.
    """

    def __init__(
        self,
        rule_policy: PolicyInterface,
        feature_spec_path: str = "trade_ai/feature_engineering/feature_spec_v1.yaml",
        model_path: Optional[str] = None,
        model_type: str = "auto",
    ):
        self.rule_policy = rule_policy
        self.mapper = FeatureMapperV1(feature_spec_path)
        self.scorer = ModelScorerV1(model_path=model_path, model_type=model_type)

    def decide(self, snapshot: SnapshotV3) -> TradeDecision:
        base = self.rule_policy.decide(snapshot)

        # Best-effort scoring. If model missing, scorer returns 1.0.
        try:
            out = self.mapper.map(snapshot.to_dict())
            score_out = self.scorer.score(out.features)
            score = float(score_out.score)
        except Exception:
            score = float(base.confidence if base.confidence is not None else 1.0)

        return TradeDecision(
            action_type=base.action_type,
            direction=base.direction,
            entry_price=base.entry_price,
            sl_price=base.sl_price,
            tp_price=base.tp_price,
            rr=base.rr,
            risk_unit=base.risk_unit,
            confidence=max(0.0, min(1.0, float(score))),
            decision_time_utc=base.decision_time_utc,
        )
