# trade_ai/application/usecases/dataset_build_usecase.py
from __future__ import annotations
from typing import Iterable, Dict, Any, Optional, Set
from ...application.ports.trade_repository import TradeRepositoryPort
from ...application.ports.snapshot_repository import SnapshotRepositoryPort
from ...application.ports.dataset_repository import DatasetRepositoryPort
from ...feature_engineering.feature_mapper_v1 import FeatureMapperV1
import uuid
import datetime
import json
from pathlib import Path


class DatasetBuildUsecase:
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
                ids = data.get("rl_exported_trade_ids", [])
                if isinstance(ids, list):
                    self._exported_trade_ids = set(str(x) for x in ids)
        except Exception:
            self._exported_trade_ids = set()

    def _save_state(self) -> None:
        try:
            self.export_state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {}
            if self.export_state_path.exists():
                try:
                    payload = json.loads(self.export_state_path.read_text(encoding="utf-8"))
                except Exception:
                    payload = {}
            payload["rl_exported_trade_ids"] = sorted(list(self._exported_trade_ids))
            self.export_state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            # export state must never crash runtime
            pass

    def build_rl_dataset_rows(self, only_new: bool = True) -> Iterable[Dict[str, Any]]:
        closed = self.trade_repo.list_closed()
        rows = []
        for t in closed:
            if only_new and t.trade_id in self._exported_trade_ids:
                continue
            entry_snap = self.snapshot_repo.get(t.entry_snapshot_id)
            exit_snap = self.snapshot_repo.get(t.exit_snapshot_id)
            if not entry_snap or not exit_snap or not t.reward_state:
                continue
            state_out = self.feature_mapper.map(entry_snap.to_dict())
            next_out = self.feature_mapper.map(exit_snap.to_dict())
            row = {
                "transition_id": str(uuid.uuid4()),
                "episode_id": t.trade_id,
                "symbol": t.symbol,
                "timestamp_entry": datetime.datetime.utcfromtimestamp(t.entry_snapshot_time_utc).isoformat() + "Z",
                "timestamp_exit": datetime.datetime.utcfromtimestamp(t.exit_snapshot_time_utc).isoformat() + "Z",
                "state_features": state_out.features,
                "state_version": entry_snap.schema_version,
                "feature_version": state_out.feature_version,
                "feature_hash": state_out.feature_hash,
                "action_type": t.decision.action_type,
                "action_rr": t.decision.rr,
                "action_sl_distance": t.decision.risk_unit,
                "action_confidence": t.decision.confidence if t.decision.confidence is not None else 1.0,
                # Optional (futures): sizing/execution meta for later learning
                "action_qty": getattr(t.execution_state, "qty", None),
                "action_notional_usdt": getattr(t.execution_state, "notional", None),
                "action_leverage": getattr(t.execution_state, "leverage", None),
                "reward": t.reward_state.pnl_r,
                "pnl_raw": t.reward_state.pnl_raw,
                "pnl_usdt": getattr(t.reward_state, "pnl_usdt", None),
                "risk_usdt": getattr(t.reward_state, "risk_usdt", None),
                "mfe": t.reward_state.mfe,
                "mae": t.reward_state.mae,
                "holding_seconds": t.reward_state.holding_seconds,
                "next_state_features": next_out.features,
                "done": True,
                "behavior_policy": {
                    "policy_name": t.policy_info.get("policy_name", "unknown"),
                    "policy_version": t.policy_info.get("policy_version", "unknown"),
                    "policy_type": t.policy_info.get("policy_type", "unknown"),
                },
                "exchange": getattr(t.execution_state, "exchange", None) or t.policy_info.get("exchange"),
                "risk_plan": t.policy_info.get("risk_plan"),
                "entry_snapshot_id": t.entry_snapshot_id,
                "exit_snapshot_id": t.exit_snapshot_id,
            }
            rows.append(row)
        return rows

    def build_and_save(self) -> int:
        rows = list(self.build_rl_dataset_rows(only_new=True))
        if rows:
            self.dataset_repo.append_rows(rows)
            # mark exported
            for r in rows:
                tid = r.get("episode_id")
                if tid:
                    self._exported_trade_ids.add(str(tid))
            self._save_state()
        return len(rows)
