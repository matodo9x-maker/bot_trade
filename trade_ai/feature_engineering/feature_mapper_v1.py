# trade_ai/feature_engineering/feature_mapper_v1.py
from __future__ import annotations
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
import numpy as np

# -----------------------
# Exceptions
# -----------------------
class FeatureMappingError(Exception):
    pass

# -----------------------
# Helpers
# -----------------------
def _is_finite(x: float) -> bool:
    return isinstance(x, (float, int)) and not (math.isnan(float(x)) or math.isinf(float(x)))

def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return float(default)
    if isinstance(v, bool):
        return float(default)
    try:
        f = float(v)
    except Exception:
        return float(default)
    return f if _is_finite(f) else float(default)

def _bool_to_float(v: Any, default: float = 0.0) -> float:
    if v is True:
        return 1.0
    if v is False:
        return 0.0
    return float(default)

def _get_by_path(obj: Dict[str, Any], path: str) -> Any:
    if not path.startswith("$."):
        raise FeatureMappingError("Path must start with $.")
    cur = obj
    for p in path[2:].split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur

# -----------------------
# Output dataclass
# -----------------------
@dataclass(frozen=True)
class FeatureMapperOutput:
    features: List[float]
    feature_version: str
    feature_hash: str

# -----------------------
# Main mapper
# -----------------------
class FeatureMapperV1:
    """
    Deterministic SnapshotV3 -> fixed-length float32 vector mapper.
    Enforces:
      - Input is dict from SnapshotV3
      - No reward/execution/future data used
      - Fixed-length output (spec.output.feature_count)
      - No NaN/Inf in output
      - Encodings deterministic
    """

    FORBIDDEN_SNAPSHOT_KEYS = {
        "decision", "execution_state", "reward_state", "risk_unit",
        "pnl", "pnl_raw", "pnl_r", "exit_price", "exit_time_utc", "tp_price", "sl_price", "rr"
    }

    def __init__(self, spec_path: Union[str, Path]):
        self.spec_path = Path(spec_path)
        self.spec = self._load_spec(self.spec_path)

        # meta
        self.feature_version = str(self.spec.get("version", "v1"))
        self.features_spec = self.spec.get("features", [])
        self.encodings = self.spec.get("encodings", {})
        out = self.spec.get("output", {})
        self.expected_count = int(out.get("feature_count", len(self.features_spec)))
        self.feature_keys = [f["key"] for f in self.features_spec]
        self.feature_hash = self._compute_feature_hash(self.feature_version, self.feature_keys)

        if self.expected_count <= 0:
            raise FeatureMappingError("spec.output.feature_count must be > 0")
        if len(self.feature_keys) != len(self.features_spec):
            raise FeatureMappingError("spec.features inconsistent")

    @staticmethod
    def _load_spec(path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FeatureMappingError(f"Spec not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise FeatureMappingError("Feature spec must be mapping")
        if "features" not in data or not isinstance(data["features"], list):
            raise FeatureMappingError("Feature spec must include 'features' list")
        return data

    @staticmethod
    def _compute_feature_hash(version: str, keys: List[str]) -> str:
        payload = version + "|" + "|".join(keys)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _assert_snapshot_ok(self, snapshot: Dict[str, Any]):
        if not isinstance(snapshot, dict):
            raise FeatureMappingError("snapshot must be dict")
        # schema version check (best-effort)
        if snapshot.get("schema_version") != "v3":
            raise FeatureMappingError("snapshot.schema_version must be 'v3'")
        # forbidden keys: prevent leakage
        overlap = set(snapshot.keys()).intersection(self.FORBIDDEN_SNAPSHOT_KEYS)
        if overlap:
            raise FeatureMappingError(f"Snapshot contains forbidden fields: {sorted(list(overlap))}")
        if "snapshot_time_utc" not in snapshot:
            raise FeatureMappingError("snapshot_time_utc missing in snapshot")

    def map(self, snapshot: Dict[str, Any]) -> FeatureMapperOutput:
        """
        snapshot: dict from SnapshotV3.to_dict()
        returns FeatureMapperOutput
        """
        self._assert_snapshot_ok(snapshot)
        vec: List[float] = []

        for idx, item in enumerate(self.features_spec):
            key = item.get("key")
            default = float(item.get("default_value", 0.0))
            # path-based
            if "path" in item:
                val = _get_by_path(snapshot, item["path"])
                typ = item.get("type", "float")
                if typ == "float":
                    out = _safe_float(val, default)
                elif typ == "bool_to_float":
                    out = _bool_to_float(val, default)
                else:
                    out = _safe_float(val, default)
                vec.append(float(out))
                continue

            # encode-based (one_hot style)
            if "encode" in item:
                enc = item["encode"]
                ref = enc.get("ref")
                value = enc.get("value")
                timeframe = enc.get("timeframe", None)
                out = self._encode_onehot(snapshot, ref, timeframe, value, default)
                vec.append(float(out))
                continue

            raise FeatureMappingError(f"Feature spec item must contain 'path' or 'encode' (key={key})")

        # final checks
        if len(vec) != self.expected_count:
            raise FeatureMappingError(f"Vector length {len(vec)} != expected {self.expected_count}")

        # no NaN/Inf; enforce numeric
        result = []
        for x in vec:
            try:
                fx = float(x)
            except Exception:
                fx = 0.0
            if not _is_finite(fx):
                fx = 0.0
            result.append(float(fx))

        # return as float32 list
        arr = np.asarray(result, dtype=np.float32).tolist()
        return FeatureMapperOutput(features=arr, feature_version=self.feature_version, feature_hash=self.feature_hash)

    def _encode_onehot(self, snapshot: Dict[str, Any], ref: str, timeframe: Optional[str], value: str, default: float) -> float:
        """
        Support encodings defined in spec. Only one_hot supported in v1.
        """
        if ref not in self.encodings:
            return float(default)
        enc_def = self.encodings[ref]
        if enc_def.get("type") != "one_hot":
            return float(default)

        # map ref → snapshot field
        if ref == "ltf_volatility_regime":
            src = _get_by_path(snapshot, "$.ltf.price.volatility_regime")
        elif ref == "ltf_hh_ll_state":
            src = _get_by_path(snapshot, "$.ltf.micro_structure.hh_ll_state")
        elif ref == "session":
            src = _get_by_path(snapshot, "$.context.session")
        elif ref.startswith("htf_"):
            # requires timeframe
            if not timeframe:
                return float(default)
            tf_obj = snapshot.get("htf", {}).get(timeframe, None)
            if not isinstance(tf_obj, dict):
                src = None
            else:
                if ref == "htf_trend":
                    src = tf_obj.get("trend")
                elif ref == "htf_market_regime":
                    src = tf_obj.get("market_regime")
                elif ref == "htf_volatility_regime":
                    src = tf_obj.get("volatility_regime")
                else:
                    src = None
        elif ref == "htf_trend" and timeframe is None:
            # fallback: not supported without timeframe
            src = None
        else:
            src = None

        return 1.0 if (src == value) else 0.0

# -----------------------
# CLI smoke test
# -----------------------
if __name__ == "__main__":
    import json, sys
    if len(sys.argv) != 3:
        print("Usage: python feature_mapper_v1.py <feature_spec.yaml> <snapshot.json>")
        sys.exit(1)
    spec = sys.argv[1]
    snap = sys.argv[2]
    mapper = FeatureMapperV1(spec)
    data = json.loads(Path(snap).read_text(encoding="utf-8"))
    out = mapper.map(data)
    print("feature_version:", out.feature_version)
    print("feature_hash:", out.feature_hash)
    print("len:", len(out.features))
    print("sample:", out.features[:8])
