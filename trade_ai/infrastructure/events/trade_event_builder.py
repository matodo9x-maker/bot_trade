# trade_ai/infrastructure/events/trade_event_builder.py
from __future__ import annotations
from typing import Dict, Any


class TradeEventBuilder:
    @staticmethod
    def build_entry_event(trade: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "trade.entry",
            "trade_id": trade.get("trade_id"),
            "symbol": trade.get("symbol"),
            "decision": trade.get("decision"),
            "policy_info": trade.get("policy_info"),
        }

    @staticmethod
    def build_exit_event(trade: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "trade.exit",
            "trade_id": trade.get("trade_id"),
            "symbol": trade.get("symbol"),
            "execution_state": trade.get("execution_state"),
            "reward_state": trade.get("reward_state"),
        }
