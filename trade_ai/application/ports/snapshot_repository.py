# trade_ai/application/ports/snapshot_repository.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from ...domain.entities.snapshot import SnapshotV3


class SnapshotRepositoryPort(ABC):
    @abstractmethod
    def save(self, snapshot: SnapshotV3) -> None:
        raise NotImplementedError()

    @abstractmethod
    def get(self, snapshot_id: str) -> Optional[SnapshotV3]:
        raise NotImplementedError()
