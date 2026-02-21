"""Backfill OHLCV history from exchange (CCXT) into Parquet.

Why:
  - Faster model training (offline) than waiting for streaming.
  - Build your own labeled datasets.

Usage:
  EXCHANGE=binance BINANCE_API_KEY=... BINANCE_API_SECRET=... \
  BOT_SYMBOL=BTCUSDT BOT_LTF=1m SINCE_UTC=2025-01-01 \
  python tools/collect_ohlcv.py

Env:
  EXCHANGE             binance|bybit|mexc
  EXCHANGE_TESTNET     0/1
  BOT_SYMBOL           e.g. BTCUSDT
  BOT_LTF              timeframe, e.g. 1m, 5m, 15m, 1h
  SINCE_UTC            ISO date/time (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
  OUT_PATH             default: data/raw/ohlcv_{exchange}_{symbol}_{tf}.parquet
  LIMIT                per request (default 1000)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from trade_ai.infrastructure.market.exchange_factory import make_exchange_from_env


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


def _parse_since(s: str) -> int:
    s = (s or "").strip()
    if not s:
        # default: last 30 days
        return int(time.time() - 30 * 86400) * 1000
    try:
        if len(s) == 10:
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
        return int(dt.timestamp()) * 1000
    except Exception:
        # fallback: treat as unix seconds
        try:
            return int(float(s)) * 1000
        except Exception:
            return int(time.time() - 30 * 86400) * 1000


def main() -> None:
    ex = make_exchange_from_env()
    ex_id = getattr(ex, "exchange_id", "unknown")
    symbol = os.getenv("BOT_SYMBOL", "BTCUSDT")
    tf = os.getenv("BOT_LTF", "1m")
    since_ms = _parse_since(os.getenv("SINCE_UTC", ""))
    limit = int(float(os.getenv("LIMIT", "1000")))

    out_path = Path(os.getenv("OUT_PATH", f"data/raw/ohlcv_{ex_id}_{symbol}_{tf}.parquet"))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    step_ms = int(_TF_SEC.get(tf, 60) * 1000)
    now_ms = int(time.time() * 1000)

    all_rows = []
    cursor = since_ms
    last_ts = None
    n_req = 0

    print(f"Collecting: exchange={ex_id} symbol={symbol} tf={tf} since_ms={since_ms} -> {out_path}")

    while cursor < now_ms:
        n_req += 1
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit, since_ms=cursor)
        if not ohlcv:
            break
        # de-dup + advance cursor
        for r in ohlcv:
            if not r or len(r) < 6:
                continue
            ts = int(r[0])
            if last_ts is not None and ts <= last_ts:
                continue
            all_rows.append({"ts_ms": ts, "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]})
            last_ts = ts
        # advance: last_ts + step
        if last_ts is None:
            break
        cursor = last_ts + step_ms

        if n_req % 10 == 0:
            print(f"requests={n_req} rows={len(all_rows)} last_ts={last_ts}")

        # small sleep to respect rate limits
        time.sleep(float(os.getenv("SLEEP_SEC", "0.2")))

        # safety
        if len(all_rows) >= int(float(os.getenv("MAX_ROWS", "500000"))):
            break

    if not all_rows:
        print("No rows collected.")
        return

    df = pd.DataFrame(all_rows).drop_duplicates(subset=["ts_ms"]).sort_values("ts_ms")
    df.to_parquet(out_path, index=False)
    print(f"Saved rows={len(df)} -> {out_path}")


if __name__ == "__main__":
    main()
