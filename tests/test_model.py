import lightgbm as lgb
import numpy as np
import pandas as pd

from scout.ml.features import CATEGORICAL, FEATURES, NUMERIC
from scout.ml.model import explain, to_model_input
from scout.ml.train import TEST_START, VAL_START, split


def test_split_is_time_based_and_purges_overlapping_labels():
    dates = pd.date_range("2020-01-01", "2025-12-31", freq="15D")
    df = pd.DataFrame({"date": dates, "future_date": dates + pd.Timedelta(days=380)})
    train, val, test = split(df)
    assert train.future_date.max() < VAL_START  # no training label resolves inside val/test
    assert train.date.max() < val.date.min() and val.date.max() < test.date.min()
    assert val.date.min() >= VAL_START and test.date.min() >= TEST_START
    assert len(train) + len(val) + len(test) < len(df)  # purged rows exist in this example


def test_explain_shap_values_add_up_to_prediction():
    rng = np.random.default_rng(0)
    n = 500
    X = pd.DataFrame({c: rng.normal(size=n) for c in NUMERIC})
    for c in CATEGORICAL:
        X[c] = rng.choice(["a", "b", "c"], size=n)
    y = X.age * 0.5 + (X.league == "a") * 0.3 + rng.normal(scale=0.1, size=n)
    model = lgb.LGBMRegressor(n_estimators=30, verbose=-1).fit(to_model_input(X), y).booster_

    out = explain(X.head(5), model, top=len(FEATURES))
    preds = model.predict(to_model_input(X.head(5)))
    for e, p in zip(out, preds):
        assert np.isclose(e["predicted_log_change"], p)
        assert np.isclose(e["base_value"] + sum(f["shap"] for f in e["factors"]), p)
    assert out[0]["factors"][0]["feature"] in {"age", "league"}
