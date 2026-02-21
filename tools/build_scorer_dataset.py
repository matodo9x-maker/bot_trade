"""Build supervised scorer dataset from closed trades.

Usage:
  python tools/build_scorer_dataset.py

Env:
  BOT_FEATURE_SPEC           (default: trade_ai/feature_engineering/feature_spec_v1.yaml)
  BOT_SCORER_DATASET_PATH    (default: data/datasets/supervised/scorer_dataset_v1.parquet)
  BOT_SNAPSHOT_DIR           (default: data/runtime/snapshots)
  BOT_TRADES_OPEN            (default: data/runtime/trades_open.csv)
  BOT_TRADES_CLOSED          (default: data/runtime/trades_closed.csv)
"""

from __future__ import annotations

import os

from trade_ai.infrastructure.storage.snapshot_repo_fs_json import SnapshotRepoFSJson
from trade_ai.infrastructure.storage.trade_repo_csv import TradeRepoCSV
from trade_ai.infrastructure.storage.dataset_repo_parquet import DatasetRepoParquet
from trade_ai.application.usecases.scorer_dataset_build_usecase import ScorerDatasetBuildUsecase


def main() -> None:
    feature_spec = os.getenv("BOT_FEATURE_SPEC", "trade_ai/feature_engineering/feature_spec_v1.yaml")

    snapshot_repo = SnapshotRepoFSJson(base_path=os.getenv("BOT_SNAPSHOT_DIR", "data/runtime/snapshots"))
    trade_repo = TradeRepoCSV(
        open_path=os.getenv("BOT_TRADES_OPEN", "data/runtime/trades_open.csv"),
        closed_path=os.getenv("BOT_TRADES_CLOSED", "data/runtime/trades_closed.csv"),
    )
    dataset_repo = DatasetRepoParquet(out_path=os.getenv("BOT_SCORER_DATASET_PATH", "data/datasets/supervised/scorer_dataset_v1.parquet"))

    uc = ScorerDatasetBuildUsecase(trade_repo, snapshot_repo, dataset_repo, feature_spec)
    n = uc.build_and_save()
    print(f"scorer_dataset_rows_appended={n}")


if __name__ == "__main__":
    main()
