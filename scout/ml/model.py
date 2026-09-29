from functools import lru_cache
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from scout.ml.features import CATEGORICAL, FEATURES

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "lgbm.txt"


@lru_cache(maxsize=1)
def load_model() -> lgb.Booster:
    return lgb.Booster(model_file=str(MODEL_PATH))


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
