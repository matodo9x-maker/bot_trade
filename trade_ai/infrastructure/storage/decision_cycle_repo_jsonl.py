# trade_ai/infrastructure/storage/decision_cycle_repo_jsonl.py
from __future__ import annotations

from typing import Any, Dict, Iterator, Optional

from .jsonl_repo import JsonlRepo


class DecisionCycleRepoJsonl:
    """Append-only decision-cycle log.

    One row per (symbol, cycle) including SKIP and BLOCK.
    Used as the canonical source for market_each_cycle dataset.
    """

    def __init__(self, path: str = "data/runtime/decision_cycles.jsonl"):
        self._repo = JsonlRepo(path)

    @property
    def path(self) -> str:
        return str(self._repo.path)

    def append(self, row: Dict[str, Any]) -> None:
        self._repo.append(row)

    def iter(self) -> Iterator[Dict[str, Any]]:
        return self._repo.iter()

    def read_all(self) -> list[Dict[str, Any]]:
        return self._repo.read_all()
