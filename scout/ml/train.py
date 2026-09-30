"""Train on 2013-2021 snapshots and evaluate on validation (2022) plus a per-year backtest.

The test years (2023-2024) are dropped on load and never seen here; see scout/ml/evaluate_test.py.
Writes models/<run_id>/ (never overwrites) and reports/m1_results.md.

Usage: uv run python -m scout.ml.train
"""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from scout.data.manifest import MANIFEST
from scout.data.raw import read_raw
from scout.data.snapshots import build_snapshots
from scout.ml.features import CATEGORICAL, FEATURES, NUMERIC, build_features
from scout.ml.model import MODELS, to_model_input

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports" / "m1_results.md"
TRAIN_YEARS = list(range(2013, 2022))
VAL_YEAR = 2022
TEST_YEARS = [2023, 2024]
BACKTEST_YEARS = list(range(2016, 2023))  # expanding window: train on 2013..y-1, evaluate on y
LGB_PARAMS = dict(n_estimators=3000, learning_rate=0.03, num_leaves=31, min_child_samples=100,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)


def build_dataset(raw: dict | None = None, years=None) -> pd.DataFrame:
    """Labelled snapshots with features. Pass years to restrict (train.py never builds the test years)."""
    raw = raw or read_raw()
    s = build_snapshots(raw, years=years or TRAIN_YEARS + [VAL_YEAR])
    s = s[s.target.notna()]
    f = build_features(s, raw)
    return pd.concat([s.drop(columns=[c for c in f.columns if c in s.columns]), f], axis=1)


def metrics(y, p) -> dict:
    y, p = np.asarray(y), np.asarray(p)
    err, moved = p - y, y != 0
    # direction: sign(prediction) == sign(actual) on snapshots whose value changed; n/a for no-change
    direction = np.nan if np.all(p == 0) else (np.sign(p[moved]) == np.sign(y[moved])).mean()
    return {"MAE": np.abs(err).mean(), "RMSE": np.sqrt((err ** 2).mean()), "Direction acc.": direction, "n": len(y)}


def mae_diff_ci(y, p_model, p_base, n_boot=1000, seed=0):
    """Bootstrap 95% CI of MAE(model) - MAE(base); negative = model better."""
    rng = np.random.default_rng(seed)
    d = np.abs(np.asarray(p_model) - y) - np.abs(np.asarray(p_base) - y)
    boots = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(n_boot)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return d.mean(), lo, hi


def linear_model():
    return make_pipeline(
        ColumnTransformer([
            ("num", make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ]),
        Ridge(alpha=1.0),
    )


def fit_predictors(train: pd.DataFrame, n_estimators: int) -> dict:
    """The four predictors, all fit on `train` only. Returns name -> predict(frame)."""
    age_curve = train.groupby(train.age.round().clip(17, 38)).target.mean()
    linear = linear_model().fit(train[FEATURES], train.target)
    gbm = lgb.LGBMRegressor(**{**LGB_PARAMS, "n_estimators": n_estimators}).fit(to_model_input(train), train.target)
    return {
        "No change": lambda d: np.zeros(len(d)),
        "Age-only (mean by age)": lambda d: d.age.round().clip(17, 38).map(age_curve).fillna(train.target.mean()).to_numpy(),
        "Linear (ridge)": lambda d: linear.predict(d[FEATURES]),
        "LightGBM": lambda d: gbm.predict(to_model_input(d)),
        "_booster": gbm.booster_,
    }


def best_iteration(train: pd.DataFrame, val: pd.DataFrame) -> int:
    gbm = lgb.LGBMRegressor(**LGB_PARAMS).fit(
        to_model_input(train), train.target, eval_X=(to_model_input(val),), eval_y=(val.target,),
        callbacks=[lgb.early_stopping(100, verbose=False)])
    return gbm.best_iteration_


def git_commit() -> str:
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    return sha + ("-dirty" if dirty else "")


def md_table(df: pd.DataFrame, fmt="{:.3f}") -> str:
    def cell(x):
        if isinstance(x, (int, np.integer)):
            return f"{x:,}"
        if isinstance(x, float):
            return "n/a" if np.isnan(x) else fmt.format(x)
        return str(x)
    rows = [[str(df.index.name or "")] + list(map(str, df.columns))]
    rows += [[str(i)] + [cell(x) for x in r] for i, r in zip(df.index, df.itertuples(index=False))]
    return "\n".join("| " + " | ".join(r) + " |" for r in [rows[0], ["---"] * len(rows[0]), *rows[1:]])


def main() -> None:
    df = build_dataset()
    assert not df.year.isin(TEST_YEARS).any()
    train, val = df[df.year.isin(TRAIN_YEARS)], df[df.year == VAL_YEAR]
    n_trees = best_iteration(train, val)
    pred = fit_predictors(train, n_trees)
    names = [k for k in pred if not k.startswith("_")]

    val_table = pd.DataFrame({m: metrics(val.target, pred[m](val)) for m in names}).T.astype({"n": int}).rename_axis("model")
    ci = {b: mae_diff_ci(val.target.to_numpy(), pred["LightGBM"](val), pred[b](val)) for b in ["No change", "Linear (ridge)"]}

    backtest = []
    for y in BACKTEST_YEARS:
        tr, ev = df[df.year < y], df[df.year == y]
        p = fit_predictors(tr, n_trees)
        backtest.append({"year": y, "n": len(ev), **{f"MAE {m}": metrics(ev.target, p[m](ev))["MAE"] for m in names},
                         "Dir. LightGBM": metrics(ev.target, p["LightGBM"](ev))["Direction acc."]})
    backtest = pd.DataFrame(backtest).set_index("year")

    contrib = pred["_booster"].predict(to_model_input(val), pred_contrib=True)[:, :-1]
    importance = pd.DataFrame({"mean abs SHAP": np.abs(contrib).mean(0)}, index=pd.Index(FEATURES, name="feature"))
    importance = importance.sort_values("mean abs SHAP", ascending=False)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = MODELS / run_id
    out.mkdir(parents=True, exist_ok=False)  # never overwrite a model
    pred["_booster"].save_model(str(out / "lgbm.txt"))
    (out / "meta.json").write_text(json.dumps({
        "run_id": run_id, "commit": git_commit(), "train_years": TRAIN_YEARS, "val_year": VAL_YEAR,
        "n_estimators": n_trees, "params": LGB_PARAMS, "features": FEATURES,
        "data_manifest": json.loads(MANIFEST.read_text()),
    }, indent=2))
    (MODELS / "LATEST").write_text(run_id)

    lines = [
        "# M1 results: validation and backtest (auto-generated by `python -m scout.ml.train`)", "",
        f"Run `{run_id}`, commit `{git_commit()}`. Train snapshots 2013–2021: {len(train):,}; validation 2022: "
        f"{len(val):,}. The test years (2023–2024) are not loaded here. LightGBM trees (early stopping on 2022): {n_trees}.", "",
        "Direction acc. = share of snapshots whose value changed where sign(prediction) == sign(actual).", "",
        "## Validation (2022 snapshots)", "", md_table(val_table), "",
        "MAE difference, LightGBM minus baseline (bootstrap 95% CI; negative = LightGBM better):", "",
        *[f"- vs {b}: {m:+.4f} [{lo:+.4f}, {hi:+.4f}]" for b, (m, lo, hi) in ci.items()], "",
        "## Backtest by year (expanding window: train on 2013..y-1, evaluate y)", "",
        "The number of trees is fixed at the value chosen on 2022. 2019 snapshots resolve in Sept 2020 (COVID dip).", "",
        md_table(backtest), "",
        "## Feature importance (mean |SHAP|, validation)", "", md_table(importance), "",
    ]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"saved models/{run_id}/")


if __name__ == "__main__":
    main()
