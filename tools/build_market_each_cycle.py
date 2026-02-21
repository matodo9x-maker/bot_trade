"""Build canonical market_each_cycle dataset (one row per cycle).

Inputs:
  - Snapshots: BOT_SNAPSHOT_DIR (default data/runtime/snapshots)
  - Decision cycles: BOT_DECISION_LOG_PATH (default data/runtime/decision_cycles.jsonl)

Output:
  - BOT_MARKET_EACH_CYCLE_PATH (default data/datasets/market/market_each_cycle_v1.parquet)

Usage:
  python tools/build_market_each_cycle.py

Options:
  REBUILD=1  -> delete output and rebuild from scratch
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from trade_ai.infrastructure.storage.snapshot_repo_fs_json import SnapshotRepoFSJson
from trade_ai.infrastructure.storage.dataset_repo_parquet import DatasetRepoParquet
from trade_ai.infrastructure.storage.decision_cycle_repo_jsonl import DecisionCycleRepoJsonl
from trade_ai.application.usecases.market_each_cycle_build_usecase import MarketEachCycleBuildUsecase


def main() -> None:
    snapshot_dir = os.getenv("BOT_SNAPSHOT_DIR", "data/runtime/snapshots")
    decision_path = os.getenv("BOT_DECISION_LOG_PATH", "data/runtime/decision_cycles.jsonl")
    out_path = os.getenv("BOT_MARKET_EACH_CYCLE_PATH", "data/datasets/market/market_each_cycle_v1.parquet")
    feature_spec = os.getenv("BOT_FEATURE_SPEC", "trade_ai/feature_engineering/feature_spec_v1.yaml")

    rebuild = str(os.getenv("REBUILD", "0")).strip().lower() in ("1", "true", "yes", "y")

    out_p = Path(out_path)
    if rebuild and out_p.exists():
        out_p.unlink()

    snapshot_repo = SnapshotRepoFSJson(base_path=snapshot_dir)
    decision_repo = DecisionCycleRepoJsonl(path=decision_path)
    out_repo = DatasetRepoParquet(out_path=out_path)

    # Incremental: skip decision_ids already present
    existing_ids = set()
    if out_p.exists() and not rebuild:
        try:
            df0 = pd.read_parquet(out_p)
            if "decision_id" in df0.columns:
                existing_ids = set([str(x) for x in df0["decision_id"].dropna().tolist()])
        except Exception:
            existing_ids = set()

    def _iter_new():
        for r in decision_repo.iter():
            did = r.get("decision_id")
            if did and str(did) in existing_ids:
                continue
            yield r

    uc = MarketEachCycleBuildUsecase(
        snapshot_repo=snapshot_repo,
        decision_cycle_iter=_iter_new(),
        out_repo=out_repo,
        feature_spec_path=feature_spec,
    )

    n = uc.build_and_append()
    print(f"OK: appended_rows={n} -> {out_path}")


if __name__ == "__main__":
    main()
