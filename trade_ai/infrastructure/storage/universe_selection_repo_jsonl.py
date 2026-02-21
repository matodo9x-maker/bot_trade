# trade_ai/infrastructure/storage/universe_selection_repo_jsonl.py
from __future__ import annotations

from typing import Any, Dict, Iterator

from .jsonl_repo import JsonlRepo


class UniverseSelectionRepoJsonl:
    """Append-only universe selection log.

    One row per refresh event.
    Used for audit and for future AI training (universe selection modeling).
    """

    def __init__(self, path: str = "data/runtime/universe_selection.jsonl"):
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
