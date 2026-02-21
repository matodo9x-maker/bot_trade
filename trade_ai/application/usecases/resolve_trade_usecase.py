# trade_ai/application/usecases/resolve_trade_usecase.py
from __future__ import annotations
from typing import Dict, Any, List
from ...application.ports.trade_repository import TradeRepositoryPort
from ...domain.entities.execution_state import ExecutionState
from ...domain.services.reward_calculator import calculate_reward


class ResolveTradeUsecase:
    def __init__(self, trade_repo: TradeRepositoryPort, event_bus=None):
        self.trade_repo = trade_repo
        self.event_bus = event_bus

    def resolve_trade(self, trade_id: str, execution: ExecutionState, ohlc_bars: List[Dict[str, Any]], exit_snapshot_id: str, exit_snapshot_time_utc: int):
        trade = self.trade_repo.get_open(trade_id)
        if trade is None:
            raise ValueError("open trade not found")
        trade.attach_execution(execution)
        if trade.execution_state.status == "CLOSED":
            trade.exit_snapshot_id = exit_snapshot_id
            trade.exit_snapshot_time_utc = exit_snapshot_time_utc
            reward = calculate_reward(trade.decision, trade.execution_state, ohlc_bars)
            trade.attach_reward(reward)
            self.trade_repo.update_closed(trade)
            if self.event_bus:
                self.event_bus.publish("trade.closed", trade.to_dict())
        else:
            self.trade_repo.save_open(trade)
