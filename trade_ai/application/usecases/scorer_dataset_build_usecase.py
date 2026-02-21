# trade_ai/application/usecases/scorer_dataset_build_usecase.py
from __future__ import annotations

from typing import Dict, Any, Iterable, Set
import uuid
import datetime
import json
from pathlib import Path

from ...application.ports.trade_repository import TradeRepositoryPort
from ...application.ports.snapshot_repository import SnapshotRepositoryPort
from ...application.ports.dataset_repository import DatasetRepositoryPort
from ...feature_engineering.feature_mapper_v1 import FeatureMapperV1


class ScorerDatasetBuildUsecase:
    """Build a supervised dataset for ML scorer training.

    Input: closed trades + entry snapshots
    Output: rows with (features, label_cls, label_reg)

    label_cls: 1 if pnl_r > 0 else 0
    label_reg: pnl_r (can be used for regression)
    """

    def __init__(
        self,
        trade_repo: TradeRepositoryPort,
        snapshot_repo: SnapshotRepositoryPort,
        dataset_repo: DatasetRepositoryPort,
        feature_spec_path: str,
        export_state_path: str = "data/runtime/dataset_export_state.json",
    ):
        self.trade_repo = trade_repo
        self.snapshot_repo = snapshot_repo
        self.dataset_repo = dataset_repo
        self.feature_mapper = FeatureMapperV1(feature_spec_path)
        self.export_state_path = Path(export_state_path)
        self._exported_trade_ids: Set[str] = set()
        self._load_state()

    def _load_state(self) -> None:
        try:
            if self.export_state_path.exists():
                data = json.loads(self.export_state_path.read_text(encoding="utf-8"))
                ids = data.get("scorer_exported_trade_ids", [])
                if isinstance(ids, list):
                    self._exported_trade_ids = set(str(x) for x in ids)
        except Exception:
            self._exported_trade_ids = set()

    def _save_state(self) -> None:
        try:
            self.export_state_path.parent.mkdir(parents=True, exist_ok=True)
            # merge with existing state keys (rl state may exist)
            payload = {}
            if self.export_state_path.exists():
                try:
                    payload = json.loads(self.export_state_path.read_text(encoding="utf-8"))
                except Exception:
                    payload = {}
            payload["scorer_exported_trade_ids"] = sorted(list(self._exported_trade_ids))
            self.export_state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def build_rows(self, only_new: bool = True) -> Iterable[Dict[str, Any]]:
        rows = []
        for t in self.trade_repo.list_closed():
            if only_new and t.trade_id in self._exported_trade_ids:
                continue
            if not t.reward_state:
                continue
            entry = self.snapshot_repo.get(t.entry_snapshot_id)
            if not entry:
                continue
            feats = self.feature_mapper.map(entry.to_dict())
            pnl_r = float(t.reward_state.pnl_r)
            label_cls = 1 if pnl_r > 0 else 0
            row = {
                "sample_id": str(uuid.uuid4()),
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "timestamp_entry": datetime.datetime.utcfromtimestamp(t.entry_snapshot_time_utc).isoformat() + "Z",
                "features": feats.features,
                "feature_version": feats.feature_version,
                "feature_hash": feats.feature_hash,
                "label_cls": int(label_cls),
                "label_reg": float(pnl_r),
                "action_type": int(t.decision.action_type),
                "rr": float(t.decision.rr),
                "sl_distance": float(t.decision.risk_unit),
                "exchange": getattr(t.execution_state, "exchange", None) or t.policy_info.get("exchange"),
            }
            rows.append(row)
        return rows

    def build_and_save(self) -> int:
        rows = list(self.build_rows(only_new=True))
        if rows:
            self.dataset_repo.append_rows(rows)
            for r in rows:
                tid = r.get("trade_id")
                if tid:
                    self._exported_trade_ids.add(str(tid))
            self._save_state()
        return len(rows)
