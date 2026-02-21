# trade_ai/application/ports/trade_repository.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional
from ...domain.entities.trade_aggregate import TradeAggregate


class TradeRepositoryPort(ABC):
    @abstractmethod
    def save_open(self, trade: TradeAggregate) -> None:
        raise NotImplementedError()

    @abstractmethod
    def update_closed(self, trade: TradeAggregate) -> None:
        raise NotImplementedError()

    @abstractmethod
    def list_closed(self) -> List[TradeAggregate]:
        raise NotImplementedError()

    @abstractmethod
    def list_open(self) -> List[TradeAggregate]:
        """List all currently OPEN trades.

        Needed for runtime loops (paper/live) to monitor open trades and
        to allow restart-safe recovery without keeping state only in RAM.
        """
        raise NotImplementedError()

    @abstractmethod
    def get_open(self, trade_id: str) -> Optional[TradeAggregate]:
        raise NotImplementedError()
