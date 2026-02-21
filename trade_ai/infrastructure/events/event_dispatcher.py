# trade_ai/infrastructure/events/event_dispatcher.py
from __future__ import annotations
from typing import Dict, Any, List


class EventDispatcher:
    """
    Minimal in-process dispatcher. In production this can be replaced with Kafka/Rabbit.
    Subscribers can register callbacks.
    """
    def __init__(self):
        self._subs = {}

    def subscribe(self, topic: str, cb):
        self._subs.setdefault(topic, []).append(cb)

    def publish(self, topic: str, payload: Dict[str, Any]):
        for cb in self._subs.get(topic, []):
            try:
                cb(topic, payload)
            except Exception:
                continue
