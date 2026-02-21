# trade_ai/application/usecases/observer_usecase.py
from __future__ import annotations
from typing import Dict
from ...application.ports.snapshot_repository import SnapshotRepositoryPort
from ...domain.entities.snapshot import SnapshotV3


class ObserverUsecase:
    def __init__(self, snapshot_repo: SnapshotRepositoryPort):
        self.snapshot_repo = snapshot_repo

    def create_snapshot(self, raw_snapshot: Dict) -> SnapshotV3:
        snap = SnapshotV3.from_dict(raw_snapshot)
        try:
            self.snapshot_repo.save(snap)
            return snap
        except Exception as e:
            # Snapshot IDs are intentionally immutable. If a snapshot already exists
            # (e.g., loop runs faster than candle close time), reuse the stored one.
            msg = str(e)
            if "immutable" in msg and "exists" in msg and hasattr(self.snapshot_repo, "get"):
                existing = self.snapshot_repo.get(snap.snapshot_id)
                if existing is not None:
                    return existing
            raise
