"""Build AI-ready universe_each_cycle dataset from universe_cycles.jsonl.

Usage:
  python tools/build_universe_each_cycle.py

Env:
  BOT_UNIVERSE_CYCLES_PATH   default: data/runtime/universe_cycles.jsonl
  OUT_PATH                  default: data/datasets/universe/universe_each_cycle_v1.parquet
  REBUILD                   0/1 (if 0 and output exists, appends by merge+dedup)

Output columns (minimum):
  timestamp_utc, exchange, symbol, selected, rank, score,
  quote_vol_usdt, atr_pct, atr_burst, spread_pct,
  funding_rate, funding_z, vol_accel, open_interest, oi_accel,
  selector_version
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

from trade_ai.infrastructure.storage.universe_cycle_repo_jsonl import UniverseCycleRepoJsonl


def main() -> None:
    cycles_path = os.getenv("BOT_UNIVERSE_CYCLES_PATH", "data/runtime/universe_cycles.jsonl")
    out_path = Path(os.getenv("OUT_PATH", "data/datasets/universe/universe_each_cycle_v1.parquet"))
    rebuild = str(os.getenv("REBUILD", "0") or "0").strip().lower() in ("1", "true", "yes", "y", "on")

    repo = UniverseCycleRepoJsonl(path=cycles_path)
    rows = list(repo.iter())
    if not rows:
        print("No universe cycle rows found.")
        return

    df = pd.DataFrame(rows)
    # keep a stable set of columns if present
    for col in [
        "timestamp_utc",
        "exchange",
        "symbol",
        "selected",
        "rank",
        "score",
        "quote_vol_usdt",
        "atr_tf",
        "atr_pct",
        "atr_burst",
        "spread_pct",
        "funding_rate",
        "funding_z",
        "vol_accel",
        "open_interest",
        "oi_accel",
        "selector_version",
    ]:
        if col not in df.columns:
            df[col] = None

    # normalize types
    if "selected" in df.columns:
        df["selected"] = df["selected"].fillna(0).astype(int)
    if "timestamp_utc" in df.columns:
        df["timestamp_utc"] = df["timestamp_utc"].astype(int)

    df = df.drop_duplicates(subset=["timestamp_utc", "symbol", "selector_version"], keep="last")
    df = df.sort_values(["timestamp_utc", "symbol"])

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not rebuild:
        try:
            old = pd.read_parquet(out_path)
            merged = pd.concat([old, df], ignore_index=True)
            merged = merged.drop_duplicates(subset=["timestamp_utc", "symbol", "selector_version"], keep="last")
            merged = merged.sort_values(["timestamp_utc", "symbol"])
            merged.to_parquet(out_path, index=False)
            print(f"Saved merged rows={len(merged)} -> {out_path}")
            return
        except Exception:
            # fallback to overwrite
            pass

    df.to_parquet(out_path, index=False)
    print(f"Saved rows={len(df)} -> {out_path}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
