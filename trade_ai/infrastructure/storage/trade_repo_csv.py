# trade_ai/infrastructure/storage/trade_repo_csv.py
from __future__ import annotations
from pathlib import Path
import csv
import json
from typing import Optional, List
from ...domain.entities.trade_aggregate import TradeAggregate
from ...domain.entities.execution_state import ExecutionState
from ...application.ports.trade_repository import TradeRepositoryPort


class TradeRepoCSV(TradeRepositoryPort):
    def __init__(self, open_path: str = "data/runtime/trades_open.csv", closed_path: str = "data/runtime/trades_closed.csv"):
        self.open_path = Path(open_path)
        self.closed_path = Path(closed_path)
        self.open_path.parent.mkdir(parents=True, exist_ok=True)
        for p in (self.open_path, self.closed_path):
            if not p.exists():
                p.write_text("trade_id,json\n", encoding="utf-8")

    def _write_row(self, path: Path, trade: TradeAggregate):
        with path.open("a", encoding="utf-8") as f:
            row = json.dumps(trade.to_dict(), ensure_ascii=False)
            f.write(f"{trade.trade_id},{row}\n")

    def save_open(self, trade: TradeAggregate) -> None:
        self._write_row(self.open_path, trade)

    def update_closed(self, trade: TradeAggregate) -> None:
        self._write_row(self.closed_path, trade)
        lines = []
        with self.open_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                tid, _ = line.split(",", 1)
                if tid.strip() != trade.trade_id:
                    lines.append(line)
        with self.open_path.open("w", encoding="utf-8") as f:
            f.writelines(lines)

    def list_closed(self) -> List[TradeAggregate]:
        out: List[TradeAggregate] = []
        with self.closed_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                # Skip header
                if line.lower().startswith("trade_id,"):
                    continue
                try:
                    _, json_blob = line.split(",", 1)
                    data = json.loads(json_blob)
                    ta = TradeAggregate.from_dict(data)
                    out.append(ta)
                except Exception:
                    # Fail-safe: ignore malformed lines
                    continue
        return out

    def list_open(self) -> List[TradeAggregate]:
        """Best-effort list of OPEN trades.

        The CSV storage is append-only for save_open(), so a trade_id may
        appear multiple times (updated states). We keep the last occurrence.
        """
        last_by_id: dict[str, TradeAggregate] = {}
        with self.open_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                if line.lower().startswith("trade_id,"):
                    continue
                try:
                    tid, json_blob = line.split(",", 1)
                    data = json.loads(json_blob)
                    ta = TradeAggregate.from_dict(data)
                    last_by_id[tid.strip()] = ta
                except Exception:
                    continue
        return list(last_by_id.values())

    def get_open(self, trade_id: str) -> Optional[TradeAggregate]:
        """Return the *latest* OPEN trade state for a given trade_id.

        Note:
          - open CSV is append-only (save_open can be called multiple times).
          - we must return the last occurrence to avoid stale state.
        """
        last: Optional[TradeAggregate] = None
        with self.open_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                if line.lower().startswith("trade_id,"):
                    continue
                try:
                    tid, json_blob = line.split(",", 1)
                    if tid.strip() != trade_id:
                        continue
                    data = json.loads(json_blob)
                    last = TradeAggregate.from_dict(data)
                except Exception:
                    continue
        return last

    def update_execution_state(self, trade_id: str, execution: ExecutionState) -> bool:
        """Update execution_state for an OPEN trade (append-only).

        Used by the runtime loop to persist order ids, qty, leverage, etc
        right after placing orders (LIVE) or simulating fills (PAPER).

        Returns:
            True if trade exists and was updated, else False.
        """
        trade = self.get_open(trade_id)
        if trade is None:
            return False
        try:
            trade.attach_execution(execution)
        except Exception:
            # If attach fails, don't corrupt storage.
            return False
        self.save_open(trade)
        return True
