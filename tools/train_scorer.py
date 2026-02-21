"""Train an ML scorer (XGB/LGBM/sklearn) from scorer dataset.

This script trains a *binary classifier*:
  y = 1 if trade pnl_r > 0 else 0

Input dataset (Parquet):
  data/datasets/supervised/scorer_dataset_v1.parquet

Output model files:
  - XGBoost : data/models/scorer_xgb_v1.json
  - LightGBM: data/models/scorer_lgbm_v1.txt
  - sklearn : data/models/scorer_sklearn_v1.joblib

Usage:
  python tools/train_scorer.py

Env:
  BOT_SCORER_DATASET_PATH  path to parquet
  SCORER_MODEL_OUT         output model path
  SCORER_MODEL_TYPE        auto|xgb|lgbm|sklearn

Notes:
  - Keep it small/cheap: default params are lightweight.
  - Always validate on paper before live.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd


def _train_test_split_time(df: pd.DataFrame, test_ratio: float = 0.2) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if "timestamp_entry" in df.columns:
        df = df.sort_values("timestamp_entry")
    n = len(df)
    cut = int(n * (1 - test_ratio))
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def main() -> None:
    in_path = Path(os.getenv("BOT_SCORER_DATASET_PATH", "data/datasets/supervised/scorer_dataset_v1.parquet"))
    model_type = (os.getenv("SCORER_MODEL_TYPE", "auto") or "auto").lower().strip()
    out_path = Path(os.getenv("SCORER_MODEL_OUT", ""))

    if not in_path.exists():
        raise SystemExit(f"Dataset not found: {in_path}")

    df = pd.read_parquet(in_path)
    if df.empty:
        raise SystemExit("Dataset is empty")

    # features is a list column
    X = np.vstack(df["features"].apply(lambda x: np.asarray(x, dtype=np.float32)).to_numpy())
    y = df["label_cls"].astype(int).to_numpy()

    train_df, test_df = _train_test_split_time(df, test_ratio=float(os.getenv("TEST_RATIO", "0.2")))
    X_train = np.vstack(train_df["features"].apply(lambda x: np.asarray(x, dtype=np.float32)).to_numpy())
    y_train = train_df["label_cls"].astype(int).to_numpy()
    X_test = np.vstack(test_df["features"].apply(lambda x: np.asarray(x, dtype=np.float32)).to_numpy())
    y_test = test_df["label_cls"].astype(int).to_numpy()

    # pick algo
    used = ""
    model = None

    def _try_xgb():
        try:
            import xgboost as xgb

            clf = xgb.XGBClassifier(
                n_estimators=int(os.getenv("XGB_N_ESTIMATORS", "300")),
                max_depth=int(os.getenv("XGB_MAX_DEPTH", "4")),
                learning_rate=float(os.getenv("XGB_LR", "0.05")),
                subsample=float(os.getenv("XGB_SUBSAMPLE", "0.9")),
                colsample_bytree=float(os.getenv("XGB_COLSAMPLE", "0.9")),
                reg_lambda=float(os.getenv("XGB_L2", "1.0")),
                objective="binary:logistic",
                eval_metric="logloss",
                n_jobs=int(os.getenv("N_JOBS", "2")),
            )
            clf.fit(X_train, y_train)
            return clf
        except Exception:
            return None

    def _try_lgbm():
        try:
            import lightgbm as lgb

            clf = lgb.LGBMClassifier(
                n_estimators=int(os.getenv("LGBM_N_ESTIMATORS", "500")),
                num_leaves=int(os.getenv("LGBM_NUM_LEAVES", "31")),
                learning_rate=float(os.getenv("LGBM_LR", "0.05")),
                subsample=float(os.getenv("LGBM_SUBSAMPLE", "0.9")),
                colsample_bytree=float(os.getenv("LGBM_COLSAMPLE", "0.9")),
                n_jobs=int(os.getenv("N_JOBS", "2")),
            )
            clf.fit(X_train, y_train)
            return clf
        except Exception:
            return None

    def _try_sklearn():
        try:
            from sklearn.ensemble import GradientBoostingClassifier

            clf = GradientBoostingClassifier(
                n_estimators=int(os.getenv("SK_N_ESTIMATORS", "300")),
                learning_rate=float(os.getenv("SK_LR", "0.05")),
                max_depth=int(os.getenv("SK_MAX_DEPTH", "3")),
            )
            clf.fit(X_train, y_train)
            return clf
        except Exception:
            return None

    if model_type in ("auto", "xgb", "xgboost"):
        model = _try_xgb()
        used = "xgb" if model is not None else ""

    if model is None and model_type in ("auto", "lgbm", "lightgbm"):
        model = _try_lgbm()
        used = "lgbm" if model is not None else ""

    if model is None:
        model = _try_sklearn()
        used = "sklearn" if model is not None else ""

    if model is None:
        raise SystemExit("Failed to train any model. Check dependencies.")

    # Evaluate
    try:
        from sklearn.metrics import roc_auc_score, accuracy_score

        if hasattr(model, "predict_proba"):
            p = model.predict_proba(X_test)[:, 1]
        else:
            p = model.predict(X_test)
        auc = float(roc_auc_score(y_test, p)) if len(set(y_test)) > 1 else None
        acc = float(accuracy_score(y_test, (p >= 0.5).astype(int)))
    except Exception:
        auc = None
        acc = None

    # Decide output path
    if not out_path:
        if used == "xgb":
            out_path = Path("data/models/scorer_xgb_v1.json")
        elif used == "lgbm":
            out_path = Path("data/models/scorer_lgbm_v1.txt")
        else:
            out_path = Path("data/models/scorer_sklearn_v1.joblib")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Save model
    if used == "xgb":
        # Save as JSON booster for lightweight inference
        try:
            model.get_booster().save_model(str(out_path))
        except Exception:
            # fallback to joblib
            import joblib

            out_path = out_path.with_suffix(".joblib")
            joblib.dump(model, str(out_path))
            used = "joblib"
    elif used == "lgbm":
        try:
            model.booster_.save_model(str(out_path))
        except Exception:
            import joblib

            out_path = out_path.with_suffix(".joblib")
            joblib.dump(model, str(out_path))
            used = "joblib"
    else:
        import joblib

        joblib.dump(model, str(out_path))

    meta = {
        "model_type": used,
        "model_path": str(out_path),
        "dataset_path": str(in_path),
        "n_samples": int(len(df)),
        "n_train": int(len(train_df)),
        "n_test": int(len(test_df)),
        "auc": auc,
        "acc": acc,
    }
    meta_path = out_path.with_suffix(out_path.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
