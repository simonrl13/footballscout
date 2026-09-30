"""80% prediction intervals: quantile LightGBM + split-conformal calibration (CQR), in plain numpy.

Fit q10/q90 models on one period, then on a later calibration period compute the conformity scores
E = max(q_lo - y, y - q_hi). The interval [q_lo - Q, q_hi + Q], with Q the ceil((n+1)(1-alpha))/n quantile
of E, has >= 1 - alpha coverage on new data exchangeable with the calibration period (Romano et al., 2019).
Time drift breaks exchangeability, so coverage is always reported per year.
"""
import numpy as np
import pandas as pd
import lightgbm as lgb

from scout.ml.model import to_model_input

ALPHA = 0.2  # 80% intervals
QUANTILE_PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=31, min_child_samples=100,
                       subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)


def fit_quantiles(train: pd.DataFrame, alpha: float = ALPHA) -> tuple[lgb.Booster, lgb.Booster]:
    lo = lgb.LGBMRegressor(objective="quantile", alpha=alpha / 2, **QUANTILE_PARAMS).fit(to_model_input(train), train.target)
    hi = lgb.LGBMRegressor(objective="quantile", alpha=1 - alpha / 2, **QUANTILE_PARAMS).fit(to_model_input(train), train.target)
    return lo.booster_, hi.booster_


def conformal_margin(y, q_lo, q_hi, alpha: float = ALPHA) -> float:
    scores = np.maximum(np.asarray(q_lo) - y, np.asarray(y) - q_hi)
    n = len(scores)
    level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


def predict_interval(X: pd.DataFrame, lo: lgb.Booster, hi: lgb.Booster, margin: float) -> tuple[np.ndarray, np.ndarray]:
    x = to_model_input(X)
    a, b = lo.predict(x) - margin, hi.predict(x) + margin
    return np.minimum(a, b), np.maximum(a, b)  # guard against crossed quantiles


def coverage_table(df: pd.DataFrame, lower, upper, by: str | None = None) -> pd.DataFrame:
    d = df.assign(_in=(df.target >= lower) & (df.target <= upper), _w=np.asarray(upper) - np.asarray(lower))
    g = d.groupby(by) if by else d.assign(_all="all").groupby("_all")
    return g.agg(n=("target", "size"), coverage=("_in", "mean"), mean_width=("_w", "mean"))


def age_band(age):
    return pd.cut(age, [0, 21, 24, 27, 30, 50], labels=["≤21", "22–24", "25–27", "28–30", "31+"], right=True)


def value_band(value):
    return pd.cut(value, [0, 1e6, 5e6, 20e6, 1e10], labels=["<€1m", "€1–5m", "€5–20m", "≥€20m"])
