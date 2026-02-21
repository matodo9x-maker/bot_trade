# trade_ai/domain/entities/snapshot.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict
import uuid


class SnapshotValidationError(Exception):
    pass


@dataclass(frozen=True)
class SnapshotV3:
    schema_version: str
    snapshot_id: str
    snapshot_time_utc: int
    symbol: str
    observer_time_utc: int
    ltf: Dict[str, Any]
    htf: Dict[str, Any]
    context: Dict[str, Any]

    @staticmethod
    def _forbidden_keys():
        return {
            "decision",
            "execution_state",
            "reward_state",
            "risk_unit",
            "pnl",
            "pnl_raw",
            "pnl_r",
            "exit_price",
            "exit_time_utc",
            "tp_price",
            "sl_price",
            "rr",
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SnapshotV3":
        if not isinstance(data, dict):
            raise SnapshotValidationError("Snapshot must be dict")

        keys_overlap = cls._forbidden_keys().intersection(set(data.keys()))
        if keys_overlap:
            raise SnapshotValidationError(f"Forbidden fields in snapshot: {keys_overlap}")

        sv = data.get("schema_version")
        if sv != "v3":
            raise SnapshotValidationError("schema_version must be 'v3'")

        snapshot_id = data.get("snapshot_id") or str(uuid.uuid4())
        snapshot_time_utc = data.get("snapshot_time_utc")
        observer_time_utc = data.get("observer_time_utc")
        if snapshot_time_utc is None or observer_time_utc is None:
            raise SnapshotValidationError("snapshot_time_utc and observer_time_utc required")
        if snapshot_time_utc > observer_time_utc:
            raise SnapshotValidationError("snapshot_time_utc must be <= observer_time_utc")

        ltf = data.get("ltf")
        if not isinstance(ltf, dict):
            raise SnapshotValidationError("ltf must be dict")

        htf = data.get("htf", {})
        context = data.get("context", {})

        return cls(
            schema_version="v3",
            snapshot_id=str(snapshot_id),
            snapshot_time_utc=int(snapshot_time_utc),
            symbol=str(data.get("symbol", "")),
            observer_time_utc=int(observer_time_utc),
            ltf=ltf,
            htf=htf,
            context=context,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "snapshot_time_utc": self.snapshot_time_utc,
            "symbol": self.symbol,
            "observer_time_utc": self.observer_time_utc,
            "ltf": self.ltf,
            "htf": self.htf,
            "context": self.context,
        }
