# trade_ai/feature_engineering/scaler.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Sequence, Optional
import numpy as np

class SimpleScaler:
    """
    Simple mean/std scaler for feature vectors.
    Save / load as JSON for traceability.
    """

    def __init__(self, mean: Optional[Sequence[float]] = None, std: Optional[Sequence[float]] = None):
        self.mean = np.array(mean, dtype=np.float32) if mean is not None else None
        self.std = np.array(std, dtype=np.float32) if std is not None else None

    def fit(self, X):
        arr = np.asarray(X, dtype=np.float32)
        self.mean = arr.mean(axis=0)
        self.std = arr.std(axis=0)
        # avoid zero std
        self.std[self.std == 0.0] = 1.0

    def transform(self, X):
        if self.mean is None or self.std is None:
            raise RuntimeError("Scaler not fitted")
        arr = np.asarray(X, dtype=np.float32)
        return ((arr - self.mean) / self.std).astype(np.float32)

    def inverse_transform(self, X):
        arr = np.asarray(X, dtype=np.float32)
        return (arr * self.std + self.mean).astype(np.float32)

    def save(self, path: str):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {"mean": self.mean.tolist(), "std": self.std.tolist()}
        p.write_text(json.dumps(data), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "SimpleScaler":
        p = Path(path)
        d = json.loads(p.read_text(encoding="utf-8"))
        return cls(mean=d["mean"], std=d["std"])
