# trade_ai/interfaces/bots/open_bot.py
from __future__ import annotations
from typing import Dict
from ...application.usecases.open_trade_usecase import OpenTradeUsecase

class OpenBot:
    def __init__(self, open_usecase: OpenTradeUsecase):
        self.open_usecase = open_usecase

    def open_from_snapshot(self, snapshot_id: str, policy_info: Dict[str,str]):
        return self.open_usecase.open_trade(snapshot_id, policy_info)
