# trade_ai/interfaces/bots/resolve_bot.py
from __future__ import annotations
from typing import Dict
from ...application.usecases.resolve_trade_usecase import ResolveTradeUsecase

class ResolveBot:
    def __init__(self, resolve_usecase: ResolveTradeUsecase):
        self.resolve_usecase = resolve_usecase

    def resolve(self, trade_id: str, execution, ohlc_bars, exit_snapshot_id: str, exit_snapshot_time_utc: int):
        return self.resolve_usecase.resolve_trade(trade_id, execution, ohlc_bars, exit_snapshot_id, exit_snapshot_time_utc)
