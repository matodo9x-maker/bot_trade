# trade_ai/infrastructure/storage/execution_event_repo_jsonl.py
from __future__ import annotations

from typing import Any, Dict, Iterator

from .jsonl_repo import JsonlRepo


class ExecutionEventRepoJsonl:
    """Append-only executions/fills log."""

    def __init__(self, path: str = "data/runtime/executions.jsonl"):
        self._repo = JsonlRepo(path)

    @property
    def path(self) -> str:
        return str(self._repo.path)

    def append(self, row: Dict[str, Any]) -> None:
        self._repo.append(row)

    def iter(self) -> Iterator[Dict[str, Any]]:
        return self._repo.iter()
