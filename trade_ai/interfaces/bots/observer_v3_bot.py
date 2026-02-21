# trade_ai/interfaces/bots/observer_v3_bot.py
from __future__ import annotations
import time
from typing import Dict
from ...application.usecases.observer_usecase import ObserverUsecase

class ObserverV3Bot:
    def __init__(self, observer_usecase: ObserverUsecase):
        self.observer_usecase = observer_usecase

    def on_market_snapshot(self, raw_snapshot: Dict):
        # raw_snapshot must be validated/normalized upstream
        snap = self.observer_usecase.create_snapshot(raw_snapshot)
        return snap
