"""Validate universe_cycles.jsonl (AI-ready per-symbol rows).

Usage:
  python tools/validate_universe_cycles.py

Checks:
- JSONL parsable
- Required keys exist
- Types are sane
- For each timestamp, selected count <= target_symbols (if present in rows)
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

from trade_ai.infrastructure.storage.universe_cycle_repo_jsonl import UniverseCycleRepoJsonl


def fail(msg: str) -> None:
    print("[FAIL]", msg)
    raise SystemExit(2)


def main() -> None:
    path = os.getenv("BOT_UNIVERSE_CYCLES_PATH", "data/runtime/universe_cycles.jsonl")
    p = Path(path)
    if not p.exists():
        fail(f"Missing universe cycles log: {p}")

    repo = UniverseCycleRepoJsonl(path=str(p))
    rows = list(repo.iter())
    if not rows:
        fail("Universe cycles log is empty")

    # Validate rows
    per_ts_selected = defaultdict(int)
    per_ts_target = {}

    for i, r in enumerate(rows[-5000:], start=max(0, len(rows) - 5000)):
        if not isinstance(r, dict):
            fail(f"Row {i} is not a dict")
        sv = str(r.get("schema_version") or "")
        if sv not in ("universe_cycle_v1",):
            fail(f"Row {i} bad schema_version={sv}")
        ts = r.get("timestamp_utc")
        if not isinstance(ts, int) or ts <= 0:
            fail(f"Row {i} invalid timestamp_utc={ts}")
        sym = str(r.get("symbol") or "").upper().replace("/", "")
        if not sym or not sym.endswith("USDT"):
            fail(f"Row {i} invalid symbol={sym}")
        sel = r.get("selected")
        if sel not in (0, 1, True, False):
            fail(f"Row {i} selected must be 0/1")
        per_ts_selected[int(ts)] += 1 if bool(sel) else 0
        if r.get("target_symbols") is not None:
            try:
                per_ts_target[int(ts)] = int(r.get("target_symbols"))
            except Exception:
                pass

        # Optional numeric sanity (non-fatal if None)
        for k in ("quote_vol_usdt", "atr_pct", "spread_pct", "funding_rate", "score"):
            v = r.get(k)
            if v is None:
                continue
            if not isinstance(v, (int, float)):
                fail(f"Row {i} {k} not numeric")

    # target constraint (best-effort)
    for ts, cnt in list(per_ts_selected.items())[-200:]:
        t = per_ts_target.get(ts)
        if t is not None and cnt > int(t):
            fail(f"timestamp={ts} selected_count={cnt} > target_symbols={t}")

    print("[OK] universe_cycles.jsonl looks valid")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
