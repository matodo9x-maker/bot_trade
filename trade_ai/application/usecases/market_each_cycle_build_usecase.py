# trade_ai/application/usecases/market_each_cycle_build_usecase.py
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

from ..ports.dataset_repository import DatasetRepositoryPort
from ..ports.snapshot_repository import SnapshotRepositoryPort
from ...feature_engineering.feature_mapper_v1 import FeatureMapperV1


class MarketEachCycleBuildUsecase:
    """Build market_each_cycle dataset from snapshots + decision_cycles log.

    Output is one row per decision cycle (including SKIP/BLOCK), with:
      - snapshot metadata
      - state_features vector
      - decision fields + gates (rule/model/risk)

    This is the canonical dataset for supervised scorer + meta-labeling.
    """

    def __init__(
        self,
        snapshot_repo: SnapshotRepositoryPort,
        decision_cycle_iter: Iterable[Dict[str, Any]],
        out_repo: DatasetRepositoryPort,
        feature_spec_path: str,
    ):
        self.snapshot_repo = snapshot_repo
        self.decision_cycle_iter = decision_cycle_iter
        self.out_repo = out_repo
        self.mapper = FeatureMapperV1(feature_spec_path)

    def build_and_append(self, max_rows: Optional[int] = None) -> int:
        rows: List[Dict[str, Any]] = []
        n = 0

        for rec in self.decision_cycle_iter:
            if not isinstance(rec, dict):
                continue
            snapshot_id = rec.get("snapshot_id")
            if not snapshot_id:
                continue
            snap = self.snapshot_repo.get(str(snapshot_id))
            if snap is None:
                continue

            feats = self.mapper.map(snap.to_dict())

            row: Dict[str, Any] = {
                # identity
                "decision_id": rec.get("decision_id"),
                "snapshot_id": snap.snapshot_id,
                "symbol": snap.symbol,
                "snapshot_time_utc": int(snap.snapshot_time_utc),
                "exchange": snap.context.get("exchange"),

                # features
                "state_features": feats.features,
                "feature_version": feats.feature_version,
                "feature_hash": feats.feature_hash,

                # convenience raw
                "ltf_tf": snap.ltf.get("tf"),
                "ltf_close": snap.ltf.get("price", {}).get("close"),
                "session": snap.context.get("session"),
                "funding_rate": snap.context.get("funding_rate"),

                # decision fields (may be missing on hard-fail)
                "action_type": rec.get("action_type"),
                "direction": rec.get("direction"),
                "entry_price": rec.get("entry_price"),
                "sl_price": rec.get("sl_price"),
                "tp_price": rec.get("tp_price"),
                "rr": rec.get("rr"),
                "risk_unit": rec.get("risk_unit"),

                # gates
                "rule_confidence": rec.get("rule_confidence"),
                "model_score": rec.get("model_score"),
                "final_confidence": rec.get("final_confidence"),
                "risk_blocked": bool(rec.get("risk_blocked", False)),
                "blocked_reason": rec.get("blocked_reason"),
                "is_opened": bool(rec.get("is_opened", False)),
                "trade_id": rec.get("trade_id"),
                "mode": rec.get("mode"),
                "cycle_time_utc": rec.get("cycle_time_utc"),
            }

            rows.append(row)
            n += 1
            if max_rows is not None and n >= int(max_rows):
                break

        if rows:
            self.out_repo.append_rows(rows)
        return int(len(rows))
