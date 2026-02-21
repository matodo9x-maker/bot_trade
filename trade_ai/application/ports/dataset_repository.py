# trade_ai/application/ports/dataset_repository.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterable, Dict, Any


class DatasetRepositoryPort(ABC):
    @abstractmethod
    def append_rows(self, rows: Iterable[Dict[str, Any]]) -> None:
        raise NotImplementedError()
