# trade_ai/domain/services/model_scorer_v1.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


class ModelScorerError(Exception):
    pass


@dataclass
class ScoreOutput:
    score: float
    model_type: str
    model_path: str


class ModelScorerV1:
    """Load + run a binary probability model (XGBoost/LightGBM/sklearn).

    - Input: 1D float feature vector
    - Output: score in [0,1]

    This is intentionally "thin". Feature generation must be done elsewhere
    (FeatureMapperV1).
    """

    def __init__(self, model_path: Optional[str] = None, model_type: str = "auto"):
        self.model_path = str(model_path) if model_path else ""
        self.model_type = (model_type or "auto").lower().strip()
        self._model = None
        self._loaded_type = "none"

        if self.model_path:
            self._load_best_effort()

    def available(self) -> bool:
        return self._model is not None

    def _load_best_effort(self) -> None:
        p = Path(self.model_path)
        if not p.exists() or not p.is_file():
            # Keep scorer disabled silently
            self._model = None
            self._loaded_type = "none"
            return

        # AUTO routing by extension
        ext = p.suffix.lower()
        want = self.model_type

        # 1) xgboost Booster JSON/UBJ
        if want in ("auto", "xgb", "xgboost") and ext in (".json", ".ubj"):
            try:
                import xgboost as xgb

                booster = xgb.Booster()
                booster.load_model(str(p))
                self._model = booster
                self._loaded_type = "xgb_booster"
                return
            except Exception:
                pass

        # 2) lightgbm Booster
        if want in ("auto", "lgbm", "lightgbm") and ext in (".txt", ".lgb"):
            try:
                import lightgbm as lgb

                booster = lgb.Booster(model_file=str(p))
                self._model = booster
                self._loaded_type = "lgb_booster"
                return
            except Exception:
                pass

        # 3) joblib/pickle sklearn/xgb classifier
        if ext in (".pkl", ".joblib"):
            try:
                import joblib

                m = joblib.load(str(p))
                self._model = m
                self._loaded_type = "joblib"
                return
            except Exception:
                pass

        # If all failed, disable
        self._model = None
        self._loaded_type = "none"

    def score(self, features: List[float]) -> ScoreOutput:
        # default: neutral score
        if self._model is None:
            return ScoreOutput(score=1.0, model_type="none", model_path=self.model_path)

        x = [float(v) for v in features]

        # xgboost Booster
        if self._loaded_type == "xgb_booster":
            import numpy as np
            import xgboost as xgb

            dmat = xgb.DMatrix(np.asarray([x], dtype=np.float32))
            pred = self._model.predict(dmat)
            s = float(pred[0]) if len(pred) else 0.5
            return ScoreOutput(score=max(0.0, min(1.0, s)), model_type="xgb_booster", model_path=self.model_path)

        # lightgbm Booster
        if self._loaded_type == "lgb_booster":
            import numpy as np

            pred = self._model.predict(np.asarray([x], dtype=np.float32))
            s = float(pred[0]) if len(pred) else 0.5
            return ScoreOutput(score=max(0.0, min(1.0, s)), model_type="lgb_booster", model_path=self.model_path)

        # sklearn-style estimator
        if self._loaded_type == "joblib":
            try:
                proba = self._model.predict_proba([x])
                # take P(class=1)
                s = float(proba[0][1])
                return ScoreOutput(score=max(0.0, min(1.0, s)), model_type="joblib", model_path=self.model_path)
            except Exception:
                # fallback: decision_function or predict
                try:
                    s = float(self._model.predict([x])[0])
                    # if predict gives 0/1
                    s = 1.0 if s >= 0.5 else 0.0
                    return ScoreOutput(score=s, model_type="joblib", model_path=self.model_path)
                except Exception:
                    return ScoreOutput(score=1.0, model_type="joblib", model_path=self.model_path)

        return ScoreOutput(score=1.0, model_type=self._loaded_type, model_path=self.model_path)
