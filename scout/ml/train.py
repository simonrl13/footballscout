"""Train on 2013-2021 snapshots and evaluate on validation (2022) plus per-year backtests. Logged to MLflow.

The test years (2023-2024) are never built here; see scout/ml/evaluate_test.py.
Model settings come from scout/ml/best_params.json (chosen by scout/ml/tune.py on validation data only).
Writes models/<run_id>/ (never overwrites) and reports/m2_results.md.

Usage: uv run --env-file .env python -m scout.ml.train
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
REPORT = ROOT / "reports" / "m2_results.md"
BEST_PARAMS = Path(__file__).with_name("best_params.json")
TRAIN_YEARS = list(range(2013, 2022))
VAL_YEAR = 2022
TEST_YEARS = [2023, 2024]
BACKTEST_YEARS = list(range(2016, 2023))  # expanding window: train on 2013..y-1, evaluate on y
INTERVAL_BACKTEST_YEARS = list(range(2017, 2023))  # quantiles fit on ..y-2, calibrated on y-1, scored on y
LGB_BASE = dict(learning_rate=0.03, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)


def best_params() -> tuple[dict, float]:
    p = json.loads(BEST_PARAMS.read_text())
    return {**LGB_BASE, **p["lightgbm"]}, float(p["ridge_alpha"])


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


def fit_predictors(train: pd.DataFrame) -> dict:
    """The four predictors, all fit on `train` only, with the tuned settings. Returns name -> predict(frame)."""
    lgb_params, alpha = best_params()
    age_curve = train.groupby(train.age.round().clip(17, 38)).target.mean()
    linear = linear_model().set_params(ridge__alpha=alpha).fit(train[FEATURES], train.target)
    gbm = lgb.LGBMRegressor(**lgb_params).fit(to_model_input(train), train.target)
    return {
        "No change": lambda d: np.zeros(len(d)),
        "Age-only (mean by age)": lambda d: d.age.round().clip(17, 38).map(age_curve).fillna(train.target.mean()).to_numpy(),
        "Linear (ridge)": lambda d: linear.predict(d[FEATURES]),
        "LightGBM": lambda d: gbm.predict(to_model_input(d)),
        "_booster": gbm.booster_,
    }


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
    from scout.ml.tracking import start_run  # first: configures MLflow before it is imported
    import mlflow
    from scout.ml.intervals import (ALPHA, age_band, conformal_margin, coverage_table, fit_quantiles,
                                    predict_interval, value_band)

    df = build_dataset()
    assert not df.year.isin(TEST_YEARS).any()
    train, val = df[df.year.isin(TRAIN_YEARS)], df[df.year == VAL_YEAR]
    lgb_params, alpha = best_params()

    with start_run("train", tags={"stage": "m2"}) as run:
        mlflow.log_params({f"lgbm_{k}": v for k, v in lgb_params.items()} | {"ridge_alpha": alpha,
                          "train_years": f"{TRAIN_YEARS[0]}-{TRAIN_YEARS[-1]}", "val_year": VAL_YEAR,
                          "n_train": len(train), "n_val": len(val), "interval_alpha": ALPHA})
        pred = fit_predictors(train)
        names = [k for k in pred if not k.startswith("_")]
        val_table = pd.DataFrame({m: metrics(val.target, pred[m](val)) for m in names}).T.astype({"n": int}).rename_axis("model")
        ci = {b: mae_diff_ci(val.target.to_numpy(), pred["LightGBM"](val), pred[b](val)) for b in ["No change", "Linear (ridge)"]}
        for m in names:
            mlflow.log_metric(f"val_mae_{m.split(' ')[0].lower()}", float(val_table.loc[m, "MAE"]))

        backtest = []
        for y in BACKTEST_YEARS:
            tr, ev = df[df.year < y], df[df.year == y]
            p = fit_predictors(tr)
            row = {"year": y, "n": len(ev), **{f"MAE {m}": metrics(ev.target, p[m](ev))["MAE"] for m in names},
                   "Dir. LightGBM": metrics(ev.target, p["LightGBM"](ev))["Direction acc."]}
            backtest.append(row)
            mlflow.log_metric("backtest_mae_lightgbm", row["MAE LightGBM"], step=y)
            mlflow.log_metric("backtest_mae_linear", row["MAE Linear (ridge)"], step=y)
        backtest = pd.DataFrame(backtest).set_index("year")

        # Intervals: quantile models on 2013-2021, conformal margin from 2022
        q_lo, q_hi = fit_quantiles(train)
        x_val = to_model_input(val)
        margin = conformal_margin(val.target.to_numpy(), q_lo.predict(x_val), q_hi.predict(x_val))
        # Honest coverage estimate without the test years: fit on ..y-2, calibrate on y-1, score y
        cov_rows, pooled = [], []
        for y in INTERVAL_BACKTEST_YEARS:
            fit, cal, ev = df[df.year <= y - 2], df[df.year == y - 1], df[df.year == y]
            lo_m, hi_m = fit_quantiles(fit)
            xc = to_model_input(cal)
            m_y = conformal_margin(cal.target.to_numpy(), lo_m.predict(xc), hi_m.predict(xc))
            lo_y, hi_y = predict_interval(ev, lo_m, hi_m, m_y)
            pooled.append(ev.assign(_lo=lo_y, _hi=hi_y))
            c = coverage_table(ev, lo_y, hi_y).iloc[0]
            cov_rows.append({"year": y, "n": int(c.n), "coverage": c.coverage, "mean width": c.mean_width, "margin": m_y})
            mlflow.log_metric("interval_backtest_coverage", float(c.coverage), step=y)
        cov_year = pd.DataFrame(cov_rows).set_index("year")
        pooled = pd.concat(pooled)
        cov_age = coverage_table(pooled.assign(age_band=age_band(pooled.age).astype(str)), pooled._lo, pooled._hi, "age_band")
        cov_value = coverage_table(pooled.assign(value_band=value_band(pooled.value_now).astype(str)), pooled._lo, pooled._hi, "value_band")
        mlflow.log_metric("interval_backtest_coverage_mean", float(cov_year.coverage.mean()))

        contrib = pred["_booster"].predict(to_model_input(val), pred_contrib=True)[:, :-1]
        importance = pd.DataFrame({"mean abs SHAP": np.abs(contrib).mean(0)}, index=pd.Index(FEATURES, name="feature"))
        importance = importance.sort_values("mean abs SHAP", ascending=False)

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = MODELS / run_id
        out.mkdir(parents=True, exist_ok=False)  # never overwrite a model
        pred["_booster"].save_model(str(out / "lgbm.txt"))
        q_lo.save_model(str(out / "q_lo.txt"))
        q_hi.save_model(str(out / "q_hi.txt"))
        meta = {"run_id": run_id, "mlflow_run_id": run.info.run_id, "commit": git_commit(), "train_years": TRAIN_YEARS,
                "val_year": VAL_YEAR, "lightgbm_params": lgb_params, "ridge_alpha": alpha, "features": FEATURES,
                "interval": {"alpha": ALPHA, "conformal_margin": margin, "calibrated_on": VAL_YEAR},
                "data_manifest": json.loads(MANIFEST.read_text())}
        (out / "meta.json").write_text(json.dumps(meta, indent=2))
        (MODELS / "LATEST").write_text(run_id)
        mlflow.log_artifacts(str(out), artifact_path="model")
        mlflow.set_tag("model_run_id", run_id)

        lines = [
            "# M2 results: validation, backtests and intervals (auto-generated by `python -m scout.ml.train`)", "",
            f"Run `{run_id}` (MLflow run `{run.info.run_id}`), commit `{git_commit()}`. Train 2013–2021: {len(train):,}; "
            f"validation 2022: {len(val):,}. Test years are not loaded here. Settings from `scout/ml/best_params.json` "
            f"(tuned on validation CV): LightGBM {json.loads(BEST_PARAMS.read_text())['lightgbm']}, ridge alpha {alpha:g}.", "",
            "## Validation (2022 snapshots)", "", md_table(val_table), "",
            "MAE difference, LightGBM minus baseline (bootstrap 95% CI; negative = LightGBM better):", "",
            *[f"- vs {b}: {m:+.4f} [{lo:+.4f}, {hi:+.4f}]" for b, (m, lo, hi) in ci.items()], "",
            "## Backtest by year (expanding window: train on 2013..y-1, evaluate y)", "",
            "2019 snapshots resolve in Sept 2020 (COVID dip).", "", md_table(backtest), "",
            "## 80% prediction intervals", "",
            "Quantile LightGBM (q10, q90) + split-conformal calibration (CQR). The saved model is fit on 2013–2021 and "
            f"calibrated on 2022 (margin {margin:+.3f} log units). Coverage is estimated **without the test years** by "
            "repeating the procedure per year: fit on ..y-2, calibrate on y-1, score y. SPEC target: 75–85%.", "",
            md_table(cov_year), "", "Pooled backtest coverage by age band:", "", md_table(cov_age), "",
            "Pooled backtest coverage by value band:", "", md_table(cov_value), "",
            "## Feature importance (mean |SHAP|, validation)", "", md_table(importance), "",
        ]
        REPORT.write_text("\n".join(lines), encoding="utf-8")
        mlflow.log_artifact(str(REPORT))
    print(f"wrote {REPORT}; saved models/{run_id}/")


if __name__ == "__main__":
    main()
