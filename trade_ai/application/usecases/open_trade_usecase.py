# trade_ai/application/usecases/open_trade_usecase.py
from __future__ import annotations
from typing import Dict, Optional
import uuid

from ...application.ports.snapshot_repository import SnapshotRepositoryPort
from ...application.ports.trade_repository import TradeRepositoryPort
from ...domain.policies.policy_interface import PolicyInterface
from ...domain.entities.trade_aggregate import TradeAggregate
from ...domain.entities.trade_decision import TradeDecision


class OpenTradeUsecase:
    def __init__(self, snapshot_repo: SnapshotRepositoryPort, trade_repo: TradeRepositoryPort, policy: PolicyInterface, event_bus=None):
        self.snapshot_repo = snapshot_repo
        self.trade_repo = trade_repo
        self.policy = policy
        self.event_bus = event_bus

    def open_trade(
        self,
        entry_snapshot_id: str,
        policy_info: Dict[str, str],
        decision_override: Optional[TradeDecision] = None,
    ) -> TradeAggregate:
        snap = self.snapshot_repo.get(entry_snapshot_id)
        if snap is None:
            raise ValueError("entry snapshot not found")
        decision = decision_override or self.policy.decide(snap)
        trade_id = str(uuid.uuid4())
        ta = TradeAggregate.create_open(
            trade_id=trade_id,
            symbol=snap.symbol,
            entry_snapshot_id=snap.snapshot_id,
            entry_snapshot_time_utc=snap.snapshot_time_utc,
            decision=decision,
            policy_info=policy_info,
        )
        self.trade_repo.save_open(ta)
        if self.event_bus:
            self.event_bus.publish("trade.open", ta.to_dict())
        return ta
