import lightgbm as lgb
import numpy as np
import pandas as pd

from scout.ml.features import CATEGORICAL, FEATURES, NUMERIC
from scout.ml.model import explain, to_model_input
from scout.ml.train import TEST_YEARS, TRAIN_YEARS, VAL_YEAR, mae_diff_ci, metrics


def test_split_years_are_disjoint_and_ordered():
    assert max(TRAIN_YEARS) < VAL_YEAR < min(TEST_YEARS)
    assert TRAIN_YEARS == list(range(2013, 2022)) and TEST_YEARS == [2023, 2024]


def test_train_module_never_evaluates_the_test_set():
    import inspect
    import scout.ml.train as train
    src = inspect.getsource(train.main)
    assert "TEST_YEARS" in src and "assert not df.year.isin(TEST_YEARS).any()" in src
    assert "evaluate_test" not in src


def test_direction_ignores_unchanged_values_and_is_na_for_no_change():
    y = np.array([0.5, -0.5, 0.0])
    assert metrics(y, np.array([0.1, -0.1, 0.3]))["Direction acc."] == 1.0
    assert np.isnan(metrics(y, np.zeros(3))["Direction acc."])


def test_mae_diff_ci_sign():
    y = np.zeros(200)
    mean, lo, hi = mae_diff_ci(y, np.full(200, 0.1), np.full(200, 0.3))
    assert mean == -0.2 or np.isclose(mean, -0.2)
    assert lo <= mean <= hi < 0


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
