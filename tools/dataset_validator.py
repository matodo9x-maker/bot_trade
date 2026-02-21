import sys
import yaml
import pandas as pd
import numpy as np
from pathlib import Path


class DatasetValidationError(Exception):
    pass


class DatasetValidator:

    def __init__(self, contract_path, dataset_path):
        self.contract_path = Path(contract_path)
        self.dataset_path = Path(dataset_path)

        self.contract = None
        self.df = None
        self.errors = []

    # -------------------------
    # LOADERS
    # -------------------------

    def load_contract(self):
        with open(self.contract_path, "r") as f:
            self.contract = yaml.safe_load(f)

    def load_dataset(self):
        self.df = pd.read_parquet(self.dataset_path)

    # -------------------------
    # VALIDATION ENTRY
    # -------------------------

    def validate(self):
        self.load_contract()
        self.load_dataset()

        self.validate_required_fields()
        self.validate_types()
        self.validate_feature_arrays()
        self.validate_business_rules()

        if self.errors:
            print("❌ DATASET VALIDATION FAILED\n")
            for e in self.errors:
                print(f"- {e}")
            sys.exit(1)
        else:
            print("✅ DATASET VALIDATION PASSED")

    # -------------------------
    # VALIDATION METHODS
    # -------------------------

    def validate_required_fields(self):
        required_fields = self.collect_required_fields(self.contract)

        for field in required_fields:
            if field not in self.df.columns:
                self.errors.append(f"Missing required field: {field}")

    def collect_required_fields(self, node, prefix=""):
        fields = []
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, dict) and value.get("required"):
                    fields.append(key)
                elif isinstance(value, dict):
                    fields += self.collect_required_fields(value)
        return fields

    def validate_types(self):
        for col in self.df.columns:
            series = self.df[col]

            if col in ["action_type"]:
                if not pd.api.types.is_integer_dtype(series):
                    self.errors.append(f"{col} must be integer")

            if col in ["reward", "pnl_raw", "mfe", "mae", "action_rr"]:
                if not pd.api.types.is_float_dtype(series):
                    self.errors.append(f"{col} must be float")

            if col == "done":
                if not pd.api.types.is_bool_dtype(series):
                    self.errors.append("done must be boolean")

    def validate_feature_arrays(self):
        if "state_features" not in self.df.columns:
            return

        lengths = self.df["state_features"].apply(len)
        if lengths.nunique() != 1:
            self.errors.append("state_features length not fixed")

        if "next_state_features" in self.df.columns:
            next_lengths = self.df["next_state_features"].apply(len)
            if not lengths.equals(next_lengths):
                self.errors.append("state_features and next_state_features length mismatch")

        # Check NaN / Inf
        for arr in self.df["state_features"]:
            if any(np.isnan(arr)):
                self.errors.append("NaN found in state_features")
                break
            if any(np.isinf(arr)):
                self.errors.append("Inf found in state_features")
                break

    def validate_business_rules(self):
        if "timestamp_entry" in self.df.columns and "timestamp_exit" in self.df.columns:
            invalid = self.df["timestamp_entry"] > self.df["timestamp_exit"]
            if invalid.any():
                self.errors.append("timestamp_entry > timestamp_exit found")

        if "action_confidence" in self.df.columns:
            invalid = ~self.df["action_confidence"].between(0, 1)
            if invalid.any():
                self.errors.append("action_confidence outside [0,1]")

        if "done" in self.df.columns:
            if not self.df["done"].all():
                self.errors.append("done must be True for trade-level RL")


# -------------------------
# CLI ENTRY
# -------------------------

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python dataset_validator.py <contract.yaml> <dataset.parquet>")
        sys.exit(1)

    contract = sys.argv[1]
    dataset = sys.argv[2]

    validator = DatasetValidator(contract, dataset)
    validator.validate()
