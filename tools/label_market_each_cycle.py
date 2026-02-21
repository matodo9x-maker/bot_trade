"""Forward labeler for market_each_cycle dataset.

Adds multi-horizon labels prefixed with y_ (no leakage into state_features).

Usage:
  EXCHANGE=binance EXCHANGE_TESTNET=0 \
  python tools/label_market_each_cycle.py

Env:
  BOT_MARKET_EACH_CYCLE_PATH       input parquet (default data/datasets/market/market_each_cycle_v1.parquet)
  BOT_MARKET_EACH_CYCLE_LABELED    output parquet (default data/datasets/market/market_each_cycle_labeled_v1.parquet)
  BOT_LTF                          timeframe (must be 5m)
  LABEL_HORIZONS                   comma list (default 1,3,6,12)
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from trade_ai.infrastructure.market.exchange_factory import make_exchange_from_env
from trade_ai.application.usecases.forward_labeler_usecase import ForwardLabelerUsecase


def main() -> None:
    in_path = os.getenv("BOT_MARKET_EACH_CYCLE_PATH", "data/datasets/market/market_each_cycle_v1.parquet")
    out_path = os.getenv("BOT_MARKET_EACH_CYCLE_LABELED", "data/datasets/market/market_each_cycle_labeled_v1.parquet")

    tf = (os.getenv("BOT_LTF", "5m") or "5m").strip().lower()
    horizons_raw = (os.getenv("LABEL_HORIZONS", "1,3,6,12") or "1,3,6,12")
    horizons = [int(x.strip()) for x in horizons_raw.split(",") if x.strip()]

    p = Path(in_path)
    if not p.exists():
        raise SystemExit(f"Missing input dataset: {in_path}")

    df = pd.read_parquet(p)

    ex = make_exchange_from_env()
    uc = ForwardLabelerUsecase(exchange=ex, tf=tf, horizons=horizons)

    df2 = uc.label_dataframe(df)

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    df2.to_parquet(out_p, index=False)

    print(f"OK: labeled_rows={len(df2)} -> {out_path}")


if __name__ == "__main__":
    main()
