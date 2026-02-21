# trade_ai/infrastructure/storage/snapshot_repo_fs_json.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional
from ...domain.entities.snapshot import SnapshotV3
from ...application.ports.snapshot_repository import SnapshotRepositoryPort


class SnapshotRepoFSJson(SnapshotRepositoryPort):
    def __init__(self, base_path: str = "data/runtime/snapshots"):
        self.base = Path(base_path)
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, snapshot_id: str) -> Path:
        return self.base / f"{snapshot_id}.json"

    def save(self, snapshot: SnapshotV3) -> None:
        p = self._path(snapshot.snapshot_id)
        if p.exists():
            raise RuntimeError("Snapshot immutable and exists")
        p.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False), encoding="utf-8")

    def get(self, snapshot_id: str) -> Optional[SnapshotV3]:
        p = self._path(snapshot_id)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return SnapshotV3.from_dict(data)
