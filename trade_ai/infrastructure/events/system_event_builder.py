# trade_ai/infrastructure/events/system_event_builder.py
from __future__ import annotations
from typing import Dict, Any


class SystemEventBuilder:
    @staticmethod
    def build_health_event(status: str = "ok") -> Dict[str, Any]:
        return {"type": "system.health", "status": status}
