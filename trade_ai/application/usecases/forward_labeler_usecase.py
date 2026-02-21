# trade_ai/application/usecases/forward_labeler_usecase.py
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

import pandas as pd


_TF_SEC = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}


class ForwardLabelerUsecase:
    """Add forward multi-horizon labels to market_each_cycle dataset.

    This uses exchange OHLCV to compute forward PnL in R-units, MFE/MAE.
    Labels are added as new columns prefixed by 'y_'.

    NOTE: This is an *offline* tool. Avoid running too frequently on large datasets.
    """

    def __init__(
        self,
        exchange,
        tf: str = "5m",
        horizons: Optional[List[int]] = None,
    ):
        self.exchange = exchange
        self.tf = (tf or "5m").strip().lower()
        self.horizons = horizons or [1, 3, 6, 12]

    def label_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        tf_sec = int(_TF_SEC.get(self.tf, 300))

        # Pre-create columns
        for h in self.horizons:
            df[f"y_fwd_pnl_r_h{h}"] = float("nan")
            df[f"y_fwd_mfe_r_h{h}"] = float("nan")
            df[f"y_fwd_mae_r_h{h}"] = float("nan")
            df[f"y_meta_win_h{h}"] = False

        # Process row-by-row (simple)
        for i, row in df.iterrows():
            symbol = row.get("symbol")
            ts = row.get("snapshot_time_utc")
            direction = (row.get("direction") or "").upper()
            entry = row.get("entry_price")
            risk_unit = row.get("risk_unit")

            if not symbol or not ts or entry is None or risk_unit in (None, 0) or direction not in ("LONG", "SHORT"):
                continue

            try:
                entry = float(entry)
                risk_unit = float(risk_unit)
            except Exception:
                continue

            if risk_unit <= 0:
                continue

            # fetch future bars starting slightly before decision time
            since_ms = int((int(ts) - 2 * tf_sec) * 1000)
            limit = int(max(self.horizons) + 5)

            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=self.tf, limit=limit, since_ms=since_ms)
            except Exception:
                ohlcv = []

            # Normalize to bars after decision ts
            bars = []
            for r in ohlcv or []:
                if not r or len(r) < 6:
                    continue
                open_ts_ms = int(r[0])
                close_ts = int((open_ts_ms + tf_sec * 1000) / 1000)
                if close_ts < int(ts):
                    continue
                bars.append({
                    "close_ts": close_ts,
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                })

            if not bars:
                continue

            # Find index where close_ts == ts (decision candle close)
            idx0 = 0
            for k, b in enumerate(bars):
                if int(b["close_ts"]) >= int(ts):
                    idx0 = k
                    break

            for h in self.horizons:
                end_idx = idx0 + int(h)
                if end_idx >= len(bars):
                    continue

                window = bars[idx0 : end_idx + 1]
                fut_close = float(window[-1]["close"])
                max_high = max(float(b["high"]) for b in window)
                min_low = min(float(b["low"]) for b in window)

                if direction == "LONG":
                    pnl_r = (fut_close - entry) / risk_unit
                    mfe_r = (max_high - entry) / risk_unit
                    mae_r = (entry - min_low) / risk_unit
                else:
                    pnl_r = (entry - fut_close) / risk_unit
                    mfe_r = (entry - min_low) / risk_unit
                    mae_r = (max_high - entry) / risk_unit

                df.at[i, f"y_fwd_pnl_r_h{h}"] = float(pnl_r)
                df.at[i, f"y_fwd_mfe_r_h{h}"] = float(mfe_r)
                df.at[i, f"y_fwd_mae_r_h{h}"] = float(mae_r)
                df.at[i, f"y_meta_win_h{h}"] = bool(pnl_r > 0)

        return df
