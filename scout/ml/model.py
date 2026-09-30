from functools import lru_cache
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from scout.ml.features import CATEGORICAL, FEATURES

MODELS = Path(__file__).resolve().parents[2] / "models"


@lru_cache(maxsize=1)
def load_model(run_id: str | None = None) -> lgb.Booster:
    """Load models/<run_id>/lgbm.txt; defaults to the run named in models/LATEST."""
    run_id = run_id or (MODELS / "LATEST").read_text().strip()
    return lgb.Booster(model_file=str(MODELS / run_id / "lgbm.txt"))


def to_model_input(X: pd.DataFrame) -> pd.DataFrame:
    return X[FEATURES].astype({c: "category" for c in CATEGORICAL})


def _py(x):
    return None if pd.isna(x) else (x.item() if hasattr(x, "item") else x)


def explain(X: pd.DataFrame, model: lgb.Booster | None = None, top: int = 5) -> list[dict]:
    """Prediction plus the top SHAP factors for each row of X (a build_features() frame).

    SHAP values come from LightGBM's built-in TreeSHAP (pred_contrib=True):
    base_value + sum of all feature contributions == predicted log change.
    """
    model = model or load_model()
    X = to_model_input(X)
    contrib = model.predict(X, pred_contrib=True)
    out = []
    for (_, row), c in zip(X.iterrows(), contrib):
        pred = float(c.sum())
        order = np.argsort(-np.abs(c[:-1]))[:top]
        out.append({
            "predicted_log_change": pred,
            "predicted_pct_change": float(np.expm1(pred)),
            "base_value": float(c[-1]),
            "factors": [{"feature": FEATURES[j], "value": _py(row.iloc[j]), "shap": float(c[j])} for j in order],
        })
    return out
