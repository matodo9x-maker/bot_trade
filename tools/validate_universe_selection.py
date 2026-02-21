"""Validate universe selection logs.

Usage:
  python tools/validate_universe_selection.py

Checks:
- JSONL parsable
- Each row has schema_version universe_v1|universe_v2
- Each row has timestamp_utc and selected symbols list
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from trade_ai.infrastructure.storage.universe_selection_repo_jsonl import UniverseSelectionRepoJsonl


def fail(msg: str) -> None:
    print("[FAIL]", msg)
    raise SystemExit(2)


def main() -> None:
    path = os.getenv("BOT_UNIVERSE_LOG_PATH", "data/runtime/universe_selection.jsonl")
    p = Path(path)
    if not p.exists():
        fail(f"Missing universe log: {p}")

    repo = UniverseSelectionRepoJsonl(path=str(p))
    rows = list(repo.iter())
    if not rows:
        fail("Universe selection log is empty")

    for i, r in enumerate(rows[-200:], start=max(0, len(rows) - 200)):
        if not isinstance(r, dict):
            fail(f"Row {i} is not a dict")
        sv = str(r.get("schema_version") or "")
        if sv not in ("universe_v1", "universe_v2", "universe_v3"):
            fail(f"Row {i} bad schema_version={sv}")
        ts = r.get("timestamp_utc")
        if not isinstance(ts, int) or ts <= 0:
            fail(f"Row {i} invalid timestamp_utc={ts}")
        sel = r.get("selected")
        if not isinstance(sel, list):
            fail(f"Row {i} selected must be list")
        if len(sel) == 0:
            # Allow empty selection only if explicitly flagged (rare)
            if not r.get("_allow_empty"):
                fail(f"Row {i} selected is empty")
        for j, it in enumerate(sel):
            if not isinstance(it, dict) or not it.get("symbol"):
                fail(f"Row {i} selected[{j}] missing symbol")
            sym = str(it.get("symbol")).upper().replace("/", "")
            if not sym.endswith("USDT"):
                # not fatal but suspicious
                fail(f"Row {i} selected[{j}] symbol not USDT-m: {sym}")

    print("[OK] universe_selection.jsonl looks valid")


if __name__ == "__main__":
    # Ensure project root in sys.path when executed from repo root
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
