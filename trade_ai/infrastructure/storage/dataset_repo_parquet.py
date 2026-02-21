# trade_ai/infrastructure/storage/dataset_repo_parquet.py
from __future__ import annotations
from pathlib import Path
from typing import Iterable, Dict, Any
import pandas as pd
import json

from ...application.ports.dataset_repository import DatasetRepositoryPort


class DatasetRepoParquet(DatasetRepositoryPort):
    def __init__(self, out_path: str = "data/datasets/rl/rl_dataset_v1.parquet"):
        self.out_path = Path(out_path)
        self.out_path.parent.mkdir(parents=True, exist_ok=True)

    def append_rows(self, rows: Iterable[Dict[str, Any]]) -> None:
        """Append rows to a single Parquet file.

        Notes:
        - This is *simple* (read+concat+rewrite) and may not scale to huge datasets.
        - If Parquet engine (pyarrow/fastparquet) is missing, we fall back to JSONL.
        """
        df = pd.DataFrame(list(rows))

        try:
            if self.out_path.exists():
                existing = pd.read_parquet(self.out_path)
                combined = pd.concat([existing, df], ignore_index=True)
                combined.to_parquet(self.out_path, index=False)
            else:
                df.to_parquet(self.out_path, index=False)
            return
        except ImportError:
            # fallback: JSONL next to parquet
            jsonl_path = self.out_path.with_suffix(".jsonl")
            jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with jsonl_path.open("a", encoding="utf-8") as f:
                for row in df.to_dict(orient="records"):
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
