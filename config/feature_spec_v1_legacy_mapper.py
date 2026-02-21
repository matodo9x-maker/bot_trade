# config/feature_spec_v1.yaml
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml


class FeatureMappingError(Exception):
    pass


def _is_finite(x: float) -> bool:
    return isinstance(x, (int, float)) and not (math.isnan(x) or math.isinf(x))


def _bool_to_float(v: Any, default: float = 0.0) -> float:
    if v is True:
        return 1.0
    if v is False:
        return 0.0
    return float(default)


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return float(default)
    if isinstance(v, bool):
        # avoid bool being treated as int
        return float(default)
    try:
        f = float(v)
    except Exception:
        return float(default)
    return f if _is_finite(f) else float(default)


def _get_by_path(obj: Dict[str, Any], path: str) -> Any:
    """
    Supports JSONPath-like dot notation used in spec:
      $.ltf.price.close
      $.htf.15m.bos
      $.context.funding_rate
    """
    if not path.startswith("$."):
        raise FeatureMappingError(f"Invalid path (must start with $.): {path}")

    parts = path[2:].split(".")
    cur: Any = obj
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


@dataclass(frozen=True)
class FeatureMapperOutput:
    features: List[float]
    feature_version: str
    feature_hash: str


class FeatureMapperV1:
    """
    Deterministic snapshot -> fixed-length vector mapper using feature_spec_v1.yaml

    Guarantees:
      - Fixed length (spec.output.feature_count)
      - Deterministic order (spec.features list order)
      - No NaN/Inf (replaced by default_value)
      - No reward/execution/future data (caller must pass Snapshot v3 only)
    """

    def __init__(self, spec_path: Union[str, Path]):
        self.spec_path = Path(spec_path)
        self.spec = self._load_spec(self.spec_path)

        self.feature_version: str = str(self.spec.get("version", "v1"))
        self.feature_keys_in_order: List[str] = [f["key"] for f in self.spec["features"]]
        self.feature_hash: str = self._compute_feature_hash(
            self.feature_version,
            self.feature_keys_in_order
        )

        out = self.spec.get("output", {})
        self.expected_count: int = int(out.get("feature_count", len(self.feature_keys_in_order)))

        # Encodings registry
        self.encodings: Dict[str, Dict[str, Any]] = self.spec.get("encodings", {})

        # Optional: if you want strict checking that spec_count matches keys
        if self.expected_count <= 0:
            raise FeatureMappingError("spec.output.feature_count must be > 0")

    @staticmethod
    def _load_spec(path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FeatureMappingError(f"Feature spec not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise FeatureMappingError("Feature spec YAML must be a mapping/object")
        if "features" not in data or not isinstance(data["features"], list):
            raise FeatureMappingError("Feature spec must include 'features' list")
        return data

    @staticmethod
    def _compute_feature_hash(feature_version: str, keys: List[str]) -> str:
        payload = feature_version + "|" + "|".join(keys)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def map(self, snapshot: Dict[str, Any]) -> FeatureMapperOutput:
        """
        snapshot: dict loaded from Snapshot v3 JSON.
        returns: FeatureMapperOutput with features + feature_version + feature_hash
        """
        vec: List[float] = []

        for spec_item in self.spec["features"]:
            key = spec_item["key"]
            default = float(spec_item.get("default_value", 0.0))

            # 1) PATH-BASED
            if "path" in spec_item:
                v = _get_by_path(snapshot, spec_item["path"])
                typ = spec_item.get("type", "float")

                if typ == "float":
                    out = _safe_float(v, default)
                elif typ == "bool_to_float":
                    out = _bool_to_float(v, default)
                else:
                    # fallback: attempt float
                    out = _safe_float(v, default)

                vec.append(out)
                continue

            # 2) ENCODE-BASED (ONE-HOT style, emits 1 dim per feature key in list)
            if "encode" in spec_item:
                enc = spec_item["encode"]
                ref = enc.get("ref")
                value = enc.get("value")
                timeframe = enc.get("timeframe")  # optional

                out = self._encode_onehot_dim(snapshot, ref, timeframe, value, default)
                vec.append(out)
                continue

            raise FeatureMappingError(f"Feature item must have 'path' or 'encode': {key}")

        # Final invariants: fixed length + finite
        if len(vec) != self.expected_count:
            raise FeatureMappingError(
                f"Feature vector length mismatch: got {len(vec)} expected {self.expected_count}. "
                f"Check spec.output.feature_count or spec.features list."
            )

        for i, x in enumerate(vec):
            if not _is_finite(float(x)):
                # safety net (should not happen)
                vec[i] = 0.0

        return FeatureMapperOutput(
            features=vec,
            feature_version=self.feature_version,
            feature_hash=self.feature_hash,
        )

    def _encode_onehot_dim(
        self,
        snapshot: Dict[str, Any],
        ref: str,
        timeframe: Optional[str],
        value: str,
        default: float,
    ) -> float:
        """
        For one-hot encodings in spec. Each encoded feature key emits 1 dimension:
          returns 1.0 if snapshot field == value else 0.0
        """
        if ref not in self.encodings:
            return float(default)

        enc_def = self.encodings[ref]
        enc_type = enc_def.get("type", "one_hot")

        if enc_type != "one_hot":
            # only one_hot supported for v1
            return float(default)

        # Determine the source field to compare based on ref
        # We infer the field names from your spec structure:
        # - ltf_volatility_regime -> $.ltf.price.volatility_regime
        # - ltf_hh_ll_state -> $.ltf.micro_structure.hh_ll_state
        # - session -> $.context.session
        # - htf_trend -> $.htf.<tf>.trend
        # - htf_market_regime -> $.htf.<tf>.market_regime
        # - htf_volatility_regime -> $.htf.<tf>.volatility_regime
        # - htf_liquidity_state -> $.htf.<tf>.liquidity_state

        source_val: Any = None

        if ref == "ltf_volatility_regime":
            source_val = _get_by_path(snapshot, "$.ltf.price.volatility_regime")
        elif ref == "ltf_hh_ll_state":
            source_val = _get_by_path(snapshot, "$.ltf.micro_structure.hh_ll_state")
        elif ref == "session":
            source_val = _get_by_path(snapshot, "$.context.session")
        elif ref.startswith("htf_"):
            if not timeframe:
                return float(default)
            # timeframe keys in snapshot are like "15m", "1h", "4h"
            # paths: $.htf.15m.trend etc.
            # We'll access dict directly to avoid path parser quirks.
            htf = snapshot.get("htf", {})
            tf_obj = htf.get(timeframe, None) if isinstance(htf, dict) else None
            if not isinstance(tf_obj, dict):
                source_val = None
            else:
                # choose field based on ref
                if ref == "htf_trend":
                    source_val = tf_obj.get("trend")
                elif ref == "htf_market_regime":
                    source_val = tf_obj.get("market_regime")
                elif ref == "htf_volatility_regime":
                    source_val = tf_obj.get("volatility_regime")
                elif ref == "htf_liquidity_state":
                    source_val = tf_obj.get("liquidity_state")
                else:
                    source_val = None
        else:
            # unknown ref
            return float(default)

        return 1.0 if (source_val == value) else 0.0


# -------------------------
# Simple CLI smoke test (optional)
# -------------------------
if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 3:
        print("Usage: python feature_mapper_v1.py <feature_spec_v1.yaml> <snapshot_v3.json>")
        sys.exit(1)

    spec_path = sys.argv[1]
    snapshot_path = sys.argv[2]

    mapper = FeatureMapperV1(spec_path)
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))

    out = mapper.map(snapshot)
    print("feature_version:", out.feature_version)
    print("feature_hash:", out.feature_hash)
    print("len(features):", len(out.features))
    print("features[:10]:", out.features[:10])
