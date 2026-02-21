# trade_ai/infrastructure/storage/universe_cycle_repo_jsonl.py
from __future__ import annotations

from typing import Any, Dict, Iterator

from .jsonl_repo import JsonlRepo


class UniverseCycleRepoJsonl:
    """Append-only universe cycle log.

    One row per (refresh_event, symbol). This is the AI-ready dataset source
    for coin-selection modeling (includes negative samples).
    """

    def __init__(self, path: str = "data/runtime/universe_cycles.jsonl"):
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
