import json
from functools import lru_cache
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from scout.ml.features import CATEGORICAL, FEATURES

MODELS = Path(__file__).resolve().parents[2] / "models"


@lru_cache(maxsize=4)
def load_run(run_id: str | None = None) -> dict:
    """Load models/<run_id>/ (default: the run named in models/LATEST): point model, and, when present,
    the q10/q90 models plus the conformal margin for 80% intervals."""
    run_id = run_id or (MODELS / "LATEST").read_text().strip()
    d = MODELS / run_id
    run = {"run_id": run_id, "model": lgb.Booster(model_file=str(d / "lgbm.txt")), "interval": None}
    if (d / "q_lo.txt").exists():
        meta = json.loads((d / "meta.json").read_text())
        run["interval"] = (lgb.Booster(model_file=str(d / "q_lo.txt")), lgb.Booster(model_file=str(d / "q_hi.txt")),
                           meta["interval"]["conformal_margin"])
    return run


def load_model(run_id: str | None = None) -> lgb.Booster:
    return load_run(run_id)["model"]


def to_model_input(X: pd.DataFrame) -> pd.DataFrame:
    return X[FEATURES].astype({c: "category" for c in CATEGORICAL})


def _py(x):
    return None if pd.isna(x) else (x.item() if hasattr(x, "item") else x)


def explain(X: pd.DataFrame, model: lgb.Booster | None = None, top: int = 5, interval=None) -> list[dict]:
    """Prediction, 80% interval (if available) and the top SHAP factors for each row of X (a build_features() frame).

    SHAP values come from LightGBM's built-in TreeSHAP (pred_contrib=True):
    base_value + sum of all feature contributions == predicted log change.
    `interval` is (q_lo, q_hi, conformal_margin); with no model given, the latest run's interval models are used.
    """
    if model is None:
        run = load_run()
        model, interval = run["model"], interval or run["interval"]
    X = to_model_input(X)
    contrib = model.predict(X, pred_contrib=True)
    lo = hi = None
    if interval is not None:
        q_lo, q_hi, margin = interval
        a, b = q_lo.predict(X) - margin, q_hi.predict(X) + margin
        lo, hi = np.minimum(a, b), np.maximum(a, b)
    out = []
    for i, ((_, row), c) in enumerate(zip(X.iterrows(), contrib)):
        pred = float(c.sum())
        order = np.argsort(-np.abs(c[:-1]))[:top]
        item = {
            "predicted_log_change": pred,
            "predicted_pct_change": float(np.expm1(pred)),
            "base_value": float(c[-1]),
            "factors": [{"feature": FEATURES[j], "value": _py(row.iloc[j]), "shap": float(c[j])} for j in order],
        }
        if lo is not None:
            item["interval_80"] = {"low_log_change": float(lo[i]), "high_log_change": float(hi[i]),
                                   "low_pct_change": float(np.expm1(lo[i])), "high_pct_change": float(np.expm1(hi[i]))}
        out.append(item)
    return out
