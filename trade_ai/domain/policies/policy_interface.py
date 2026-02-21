# trade_ai/domain/policies/policy_interface.py
from __future__ import annotations
from abc import ABC, abstractmethod
from ..entities.snapshot import SnapshotV3
from ..entities.trade_decision import TradeDecision


class PolicyInterface(ABC):
    @abstractmethod
    def decide(self, snapshot: SnapshotV3) -> TradeDecision:
        raise NotImplementedError()
