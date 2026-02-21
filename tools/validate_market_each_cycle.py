"""Validate market_each_cycle parquet dataset.

Usage:
  python tools/validate_market_each_cycle.py

Env:
  BOT_MARKET_EACH_CYCLE_PATH default data/datasets/market/market_each_cycle_v1.parquet
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> None:
    path = os.getenv("BOT_MARKET_EACH_CYCLE_PATH", "data/datasets/market/market_each_cycle_v1.parquet")
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Missing dataset: {path}")

    df = pd.read_parquet(p)

    required = [
        "decision_id",
        "snapshot_id",
        "symbol",
        "snapshot_time_utc",
        "state_features",
        "feature_version",
        "feature_hash",
        "ltf_tf",
    ]

    errors = []

    for k in required:
        if k not in df.columns:
            errors.append(f"missing column: {k}")

    if "ltf_tf" in df.columns:
        bad = df["ltf_tf"].astype(str).str.lower().ne("5m")
        if bad.any():
            errors.append(f"ltf_tf must be 5m (bad_rows={int(bad.sum())})")

    if "state_features" in df.columns and len(df) > 0:
        lens = df["state_features"].apply(lambda x: len(x) if isinstance(x, (list, tuple, np.ndarray)) else -1)
        if (lens <= 0).any():
            errors.append(f"state_features contains non-array values (bad_rows={int((lens<=0).sum())})")
        if lens.nunique() != 1:
            errors.append(f"state_features length not fixed (unique_lengths={lens.nunique()})")

        # NaN/Inf checks
        for idx, arr in enumerate(df["state_features"].head(5000)):
            if not isinstance(arr, (list, tuple, np.ndarray)):
                continue
            a = np.array(arr, dtype=float)
            if np.isnan(a).any():
                errors.append(f"NaN found in state_features at row {idx}")
                break
            if np.isinf(a).any():
                errors.append(f"Inf found in state_features at row {idx}")
                break

    # Leakage guard: these columns should NOT exist in market_each_cycle (they belong to trade-level or labels)
    forbidden_cols = {"reward", "pnl_raw", "pnl_r", "mfe", "mae", "done", "next_state_features"}
    inter = forbidden_cols.intersection(set(df.columns))
    if inter:
        errors.append(f"forbidden columns present: {sorted(list(inter))}")

    if errors:
        print("❌ market_each_cycle validation FAILED")
        for e in errors:
            print("-", e)
        sys.exit(1)

    print(f"✅ market_each_cycle validation PASSED (rows={len(df)} cols={len(df.columns)})")


if __name__ == "__main__":
    main()
