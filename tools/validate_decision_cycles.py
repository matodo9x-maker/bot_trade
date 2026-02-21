"""Validate decision_cycles.jsonl against basic schema + no-leak invariants.

Usage:
  python tools/validate_decision_cycles.py

Env:
  BOT_DECISION_LOG_PATH  default data/runtime/decision_cycles.jsonl
  BOT_SNAPSHOT_DIR       default data/runtime/snapshots
  MAX_ROWS               optional cap for speed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from trade_ai.infrastructure.storage.decision_cycle_repo_jsonl import DecisionCycleRepoJsonl
from trade_ai.infrastructure.storage.snapshot_repo_fs_json import SnapshotRepoFSJson


def _is_num(x) -> bool:
    try:
        float(x)
        return True
    except Exception:
        return False


def main() -> None:
    path = os.getenv("BOT_DECISION_LOG_PATH", "data/runtime/decision_cycles.jsonl")
    snap_dir = os.getenv("BOT_SNAPSHOT_DIR", "data/runtime/snapshots")
    max_rows = int(float(os.getenv("MAX_ROWS", "0") or "0"))

    repo = DecisionCycleRepoJsonl(path=path)
    snap_repo = SnapshotRepoFSJson(base_path=snap_dir)

    required = ["schema_version", "decision_id", "snapshot_id", "snapshot_time_utc", "symbol", "mode", "is_opened"]

    errors = []
    n = 0

    for r in repo.iter():
        n += 1
        for k in required:
            if k not in r:
                errors.append(f"row#{n}: missing {k}")

        # type checks
        if r.get("schema_version") not in ("v1", "1", 1):
            errors.append(f"row#{n}: schema_version must be v1")

        if not str(r.get("decision_id") or "").strip():
            errors.append(f"row#{n}: decision_id empty")

        if not str(r.get("snapshot_id") or "").strip():
            errors.append(f"row#{n}: snapshot_id empty")

        if r.get("is_opened") and not str(r.get("trade_id") or "").strip():
            errors.append(f"row#{n}: is_opened=1 requires trade_id")

        # confidence range
        for ck in ("rule_confidence", "model_score", "final_confidence"):
            v = r.get(ck)
            if v is None:
                continue
            if not _is_num(v):
                errors.append(f"row#{n}: {ck} not numeric")
                continue
            fv = float(v)
            if fv < 0.0 or fv > 1.0:
                errors.append(f"row#{n}: {ck} out of [0,1]")

        # snapshot invariants (best-effort)
        sid = r.get("snapshot_id")
        snap = snap_repo.get(str(sid))
        if snap is not None:
            if (snap.ltf.get("timestamp") is not None) and int(snap.ltf.get("timestamp")) != int(snap.snapshot_time_utc):
                errors.append(f"row#{n}: snapshot ltf.timestamp != snapshot_time_utc")
            if str(snap.ltf.get("tf") or "").strip().lower() != "5m":
                errors.append(f"row#{n}: snapshot ltf.tf must be 5m")
            htf = snap.htf or {}
            needed = {"15m", "1h", "4h"}
            if not needed.issubset(set([str(x).lower() for x in htf.keys()])):
                errors.append(f"row#{n}: snapshot missing required HTF {sorted(needed)}")

        if max_rows and n >= max_rows:
            break

    if errors:
        print("❌ decision_cycles validation FAILED")
        for e in errors[:200]:
            print("-", e)
        if len(errors) > 200:
            print(f"... ({len(errors)-200} more)")
        sys.exit(1)

    print(f"✅ decision_cycles validation PASSED (rows={n})")


if __name__ == "__main__":
    main()
