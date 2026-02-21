# trade_ai/infrastructure/storage/jsonl_repo.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional


class JsonlRepo:
    """Simple append-only JSONL repository.

    - One object per line (UTF-8)
    - Best-effort fsync to reduce data loss on crashes
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, obj: Dict[str, Any]) -> None:
        if not isinstance(obj, dict):
            raise TypeError("JsonlRepo.append expects a dict")
        # Add write timestamp if not present
        obj.setdefault("_write_time_utc", int(time.time()))
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            try:
                f.flush()
            except Exception:
                pass

    def iter(self) -> Iterator[Dict[str, Any]]:
        if not self.path.exists():
            return iter(())
        def _gen() -> Iterator[Dict[str, Any]]:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            yield obj
                    except Exception:
                        continue
        return _gen()

    def read_all(self) -> list[Dict[str, Any]]:
        return list(self.iter())
