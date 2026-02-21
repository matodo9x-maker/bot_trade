# trade_ai/application/ports/event_bus_port.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, Any


class EventBusPort(ABC):
    @abstractmethod
    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        raise NotImplementedError()
