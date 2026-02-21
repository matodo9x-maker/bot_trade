# trade_ai/domain/entities/trade_aggregate.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
from .trade_decision import TradeDecision
from .execution_state import ExecutionState
from .reward_state import RewardState
import copy


class TradeAggregateError(Exception):
    pass


@dataclass
class TradeAggregate:
    schema_version: str
    trade_id: str
    symbol: str
    entry_snapshot_id: str
    exit_snapshot_id: Optional[str]
    entry_snapshot_time_utc: int
    exit_snapshot_time_utc: Optional[int]
    decision: TradeDecision
    execution_state: ExecutionState
    reward_state: Optional[RewardState]
    policy_info: Dict[str, Any]

    @classmethod
    def create_open(cls, trade_id: str, symbol: str, entry_snapshot_id: str,
                    entry_snapshot_time_utc: int, decision: TradeDecision, policy_info: Dict[str, Any]):
        exec_state = ExecutionState(status="OPEN")
        return cls(
            schema_version="v3",
            trade_id=trade_id,
            symbol=symbol,
            entry_snapshot_id=entry_snapshot_id,
            exit_snapshot_id=None,
            entry_snapshot_time_utc=entry_snapshot_time_utc,
            exit_snapshot_time_utc=None,
            decision=decision,
            execution_state=exec_state,
            reward_state=None,
            policy_info=policy_info,
        )

    def attach_execution(self, execution: ExecutionState):
        if self.execution_state.status == "CLOSED":
            raise TradeAggregateError("execution already closed")
        # Allow updating entry fills (OPEN) and/or closing.
        # In practice, many runtimes only know entry fill at close time
        # (or they close without persisting an intermediate OPEN fill state).
        # Therefore we accept entry_* fields on CLOSED execution too.

        # Update entry info if provided.
        if execution.entry_time_utc is not None:
            self.execution_state.entry_time_utc = execution.entry_time_utc
        if execution.entry_fill_price is not None:
            self.execution_state.entry_fill_price = execution.entry_fill_price

        # Copy optional futures/runtime metadata (backward compatible).
        for attr in (
            "exchange",
            "account_type",
            "margin_mode",
            "position_mode",
            "leverage",
            "qty",
            "notional",
            "entry_order_id",
            "tp_order_id",
            "sl_order_id",
            "client_order_id",
        ):
            try:
                v = getattr(execution, attr)
                if v is not None:
                    setattr(self.execution_state, attr, v)
            except Exception:
                continue

        if execution.status == "OPEN":
            # update fees/funding (entry-side)
            self.execution_state.fees_total = execution.fees_total
            self.execution_state.funding_paid = execution.funding_paid
            return

        # closing
        self.execution_state.exit_time_utc = execution.exit_time_utc
        self.execution_state.exit_fill_price = execution.exit_fill_price
        self.execution_state.exit_type = execution.exit_type
        self.execution_state.fees_total = execution.fees_total
        self.execution_state.funding_paid = execution.funding_paid
        self.execution_state.status = "CLOSED"

    def attach_reward(self, reward: RewardState):
        if self.execution_state.status != "CLOSED":
            raise TradeAggregateError("cannot attach reward unless trade is CLOSED")
        self.reward_state = reward

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "entry_snapshot_id": self.entry_snapshot_id,
            "exit_snapshot_id": self.exit_snapshot_id,
            "entry_snapshot_time_utc": self.entry_snapshot_time_utc,
            "exit_snapshot_time_utc": self.exit_snapshot_time_utc,
            "decision": copy.deepcopy(self.decision.__dict__),
            "execution_state": copy.deepcopy(self.execution_state.__dict__),
            "reward_state": (copy.deepcopy(self.reward_state.__dict__) if self.reward_state else None),
            "policy_info": copy.deepcopy(self.policy_info),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradeAggregate":
        """Reconstruct a TradeAggregate (and nested domain objects) from dict.

        The CSV repo originally stored JSON blobs but could not deserialize
        decision/execution/reward, which made dataset building impossible.
        This method is the canonical hydrator.
        """
        if not isinstance(data, dict):
            raise TradeAggregateError("TradeAggregate.from_dict expects a dict")

        d = data.get("decision")
        if not isinstance(d, dict):
            raise TradeAggregateError("Missing/invalid decision")
        decision = TradeDecision(**d)

        e = data.get("execution_state")
        if not isinstance(e, dict):
            raise TradeAggregateError("Missing/invalid execution_state")
        execution_state = ExecutionState(**e)

        r = data.get("reward_state")
        reward_state = RewardState(**r) if isinstance(r, dict) else None

        return cls(
            schema_version=str(data.get("schema_version", "v3")),
            trade_id=str(data.get("trade_id")),
            symbol=str(data.get("symbol")),
            entry_snapshot_id=str(data.get("entry_snapshot_id")),
            exit_snapshot_id=(str(data["exit_snapshot_id"]) if data.get("exit_snapshot_id") else None),
            entry_snapshot_time_utc=int(data.get("entry_snapshot_time_utc", 0)),
            exit_snapshot_time_utc=(int(data["exit_snapshot_time_utc"]) if data.get("exit_snapshot_time_utc") is not None else None),
            decision=decision,
            execution_state=execution_state,
            reward_state=reward_state,
            policy_info=dict(data.get("policy_info", {}) or {}),
        )
