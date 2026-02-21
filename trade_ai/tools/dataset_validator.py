# trade_ai/tools/dataset_validator.py
import yaml
import pandas as pd
import numpy as np
import sys
from pathlib import Path

class DatasetValidationError(Exception):
    pass

class DatasetValidator:
    def __init__(self, contract_path: str, dataset_path: str):
        self.contract = yaml.safe_load(Path(contract_path).read_text(encoding="utf-8"))
        self.df = pd.read_parquet(dataset_path)
        self.errors = []

    def validate(self):
        self._validate_required_fields()
        self._validate_types()
        self._validate_feature_arrays()
        self._validate_business_rules()
        if self.errors:
            raise DatasetValidationError("\n".join(self.errors))
        return True
# inside _validate_business_rules()
        if "action_rr" in self.df.columns:
            if (self.df["action_rr"] <= 0).any():
              self.errors.append("action_rr must be > 0")


    def _validate_required_fields(self):
        required = []
        def collect(node):
            if isinstance(node, dict):
                for k,v in node.items():
                    if isinstance(v, dict) and v.get("required"):
                        required.append(k)
                    elif isinstance(v, dict):
                        collect(v)
        collect(self.contract)
        for f in required:
            if f not in self.df.columns:
                self.errors.append(f"Missing required field: {f}")

    def _validate_types(self):
        if "action_type" in self.df.columns:
            if not pd.api.types.is_integer_dtype(self.df["action_type"]):
                self.errors.append("action_type must be integer")
        floats = ["reward","pnl_raw","mfe","mae","action_rr","action_sl_distance"]
        for f in floats:
            if f in self.df.columns and not pd.api.types.is_float_dtype(self.df[f]):
                self.errors.append(f"{f} must be float")
        if "done" in self.df.columns and not pd.api.types.is_bool_dtype(self.df["done"]):
            self.errors.append("done must be bool")

    def _validate_feature_arrays(self):
        if "state_features" not in self.df.columns:
            self.errors.append("state_features missing")
            return
        lengths = self.df["state_features"].apply(lambda x: len(x) if hasattr(x,'__len__') else -1)
        if lengths.nunique() != 1:
            self.errors.append("state_features length not fixed")
        if "next_state_features" in self.df.columns:
            nl = self.df["next_state_features"].apply(lambda x: len(x) if hasattr(x,'__len__') else -1)
            if not lengths.equals(nl):
                self.errors.append("state and next_state length mismatch")
        # NaN/Inf check
        for arr in self.df["state_features"].tolist():
            a = np.asarray(arr, dtype=np.float64)
            if np.isnan(a).any() or np.isinf(a).any():
                self.errors.append("NaN/Inf in state_features")
                break

    def _validate_business_rules(self):
        if "timestamp_entry" in self.df.columns and "timestamp_exit" in self.df.columns:
            if (pd.to_datetime(self.df["timestamp_entry"]) > pd.to_datetime(self.df["timestamp_exit"])).any():
                self.errors.append("timestamp_entry > timestamp_exit found")
        if "action_confidence" in self.df.columns:
            if (~self.df["action_confidence"].between(0,1)).any():
                self.errors.append("action_confidence outside [0,1]")
        if "done" in self.df.columns:
            if not self.df["done"].all():
                self.errors.append("done must be True")
        # reward consistency
        if set(["reward","pnl_raw","action_sl_distance"]).issubset(set(self.df.columns)):
            # allow small numeric tolerance
            diff = np.abs(self.df["reward"] - (self.df["pnl_raw"] / self.df["action_sl_distance"]))
            if (diff > 1e-6).any():
                self.errors.append("reward != pnl_raw / action_sl_distance (consistency check failed)")
        # action_type allowed values
        if "action_type" in self.df.columns:
            if not self.df["action_type"].isin([0,1]).all():
                self.errors.append("action_type must be 0 or 1")
