"""M2 improvement pass, validation data only (never the test years).

1. Rolling-origin CV over earlier seasons: for y in 2016..2021, fit on 2013..y-1 and evaluate on y.
2. A small LightGBM grid (incl. MAE-oriented l1/huber losses) and, for fairness, a ridge alpha grid;
   each model family picks its config by mean CV MAE.
3. The two picks are compared once on the 2022 validation year, with bootstrap CIs.
4. Error breakdown (pooled CV folds + 2022) by position, age band and value band: where does LightGBM beat linear?

Writes scout/ml/best_params.json (read by train.py) and reports/m2_tuning.md; logs every config to MLflow.
Usage: uv run --env-file .env python -m scout.ml.tune
"""
import itertools
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from scout.ml.intervals import age_band, value_band
from scout.ml.model import to_model_input
from scout.ml.tracking import start_run
from scout.ml.train import (ROOT, TEST_YEARS, TRAIN_YEARS, VAL_YEAR, build_dataset, git_commit, linear_model,
                            mae_diff_ci, md_table)

BEST = Path(__file__).with_name("best_params.json")
REPORT = ROOT / "reports" / "m2_tuning.md"
CV_YEARS = list(range(2016, 2022))
BASE = dict(learning_rate=0.03, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)
GRID = {"objective": ["l2", "l1", "huber"], "num_leaves": [7, 15, 31], "min_child_samples": [50, 200],
        "n_estimators": [150, 300, 600]}
RIDGE_ALPHAS = [0.1, 1.0, 10.0, 100.0, 1000.0]


def lgbm_predict(train, test, params):
    m = lgb.LGBMRegressor(**BASE, **params).fit(to_model_input(train), train.target)
    return m.predict(to_model_input(test))


def ridge_predict(train, test, alpha):
    m = linear_model().set_params(ridge__alpha=alpha).fit(train, train.target)
    return m.predict(test)


def cv_mae(df, predict, cfg) -> tuple[float, dict]:
    per_year = {}
    for y in CV_YEARS:
        tr, ev = df[df.year < y], df[df.year == y]
        per_year[y] = float(np.abs(predict(tr, ev, cfg) - ev.target).mean())
    return float(np.mean(list(per_year.values()))), per_year


def cv_predictions(df, predict, cfg) -> pd.DataFrame:
    parts = []
    for y in CV_YEARS + [VAL_YEAR]:
        tr, ev = df[df.year < y], df[df.year == y]
        parts.append(ev.assign(pred=predict(tr, ev, cfg)))
    return pd.concat(parts)


def breakdown(lgb_pred: pd.DataFrame, lin_pred: pd.DataFrame, by: pd.Series, name: str) -> pd.DataFrame:
    rows = []
    y = lgb_pred.target.to_numpy()
    for g in pd.unique(by.dropna()):
        m = (by == g).to_numpy()
        diff, lo, hi = mae_diff_ci(y[m], lgb_pred.pred.to_numpy()[m], lin_pred.pred.to_numpy()[m], n_boot=500)
        rows.append({name: g, "n": int(m.sum()), "MAE linear": np.abs(lin_pred.pred.to_numpy()[m] - y[m]).mean(),
                     "MAE LightGBM": np.abs(lgb_pred.pred.to_numpy()[m] - y[m]).mean(),
                     "diff": diff, "95% CI": f"[{lo:+.3f}, {hi:+.3f}]",
                     "LightGBM better?": "yes" if hi < 0 else ("no (linear better)" if lo > 0 else "tie")})
    return pd.DataFrame(rows).set_index(name).sort_index()


def main() -> None:
    df = build_dataset()
    assert not df.year.isin(TEST_YEARS).any()
    dev = df[df.year.isin(TRAIN_YEARS)]
    configs = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
    results = []
    with start_run("tune", tags={"stage": "m2-improvement-pass"}) as parent:
        import mlflow
        for cfg in configs:
            mean, per_year = cv_mae(dev, lgbm_predict, cfg)
            results.append({"family": "LightGBM", **cfg, "cv_mae": mean})
            with mlflow.start_run(nested=True, run_name=f"lgbm {cfg}"):
                mlflow.log_params({"family": "LightGBM", **cfg})
                mlflow.log_metrics({"cv_mae": mean, **{f"cv_mae_{y}": v for y, v in per_year.items()}})
        for a in RIDGE_ALPHAS:
            mean, per_year = cv_mae(dev, ridge_predict, a)
            results.append({"family": "Ridge", "alpha": a, "cv_mae": mean})
            with mlflow.start_run(nested=True, run_name=f"ridge alpha={a}"):
                mlflow.log_params({"family": "Ridge", "alpha": a})
                mlflow.log_metrics({"cv_mae": mean, **{f"cv_mae_{y}": v for y, v in per_year.items()}})
        res = pd.DataFrame(results)
        best_lgb = res[res.family == "LightGBM"].sort_values("cv_mae").iloc[0]
        best_ridge = res[res.family == "Ridge"].sort_values("cv_mae").iloc[0]
        # the results frame mixes families (NaN columns), so ints come back as floats: cast by the grid's own types
        lgb_cfg = {k: type(GRID[k][0])(best_lgb[k]) for k in GRID}
        alpha = float(best_ridge.alpha)
        default_cfg = {"objective": "l2", "num_leaves": 31, "min_child_samples": 100, "n_estimators": 226}  # M1 model

        # One comparison on 2022 (validation), fit on 2013-2021
        val = df[df.year == VAL_YEAR]
        p = {"No change": np.zeros(len(val)),
             "Linear (M1, alpha=1)": ridge_predict(dev, val, 1.0),
             f"Linear (tuned, alpha={alpha:g})": ridge_predict(dev, val, alpha),
             "LightGBM (M1 settings)": lgbm_predict(dev, val, default_cfg),
             "LightGBM (tuned)": lgbm_predict(dev, val, lgb_cfg)}
        y = val.target.to_numpy()
        val_table = pd.DataFrame({k: {"MAE": np.abs(v - y).mean(), "RMSE": np.sqrt(((v - y) ** 2).mean())} for k, v in p.items()}).T
        val_table.index.name = "model (fit 2013–2021, scored on 2022)"
        d, lo, hi = mae_diff_ci(y, p["LightGBM (tuned)"], p[f"Linear (tuned, alpha={alpha:g})"])
        mlflow.log_params({f"best_lgbm_{k}": v for k, v in lgb_cfg.items()} | {"best_ridge_alpha": alpha})
        mlflow.log_metrics({"val_mae_lgbm_tuned": val_table.loc["LightGBM (tuned)", "MAE"],
                            "val_mae_linear_tuned": val_table.iloc[2]["MAE"], "val_diff": d, "val_diff_lo": lo, "val_diff_hi": hi})

        # Where does LightGBM beat linear? Pooled CV folds + 2022, both tuned.
        lg = cv_predictions(df, lgbm_predict, lgb_cfg)
        ln = cv_predictions(df, ridge_predict, alpha)
        tables = {
            "position": breakdown(lg, ln, lg.position, "position"),
            "age band": breakdown(lg, ln, age_band(lg.age).astype(str), "age band"),
            "value band": breakdown(lg, ln, value_band(lg.value_now).astype(str), "value band"),
            "year": breakdown(lg, ln, lg.year, "year"),
        }

    BEST.write_text(json.dumps({"lightgbm": lgb_cfg, "ridge_alpha": alpha, "chosen_by": "mean rolling-origin CV MAE, 2016-2021",
                                "commit": git_commit()}, indent=2) + "\n")
    top = (res[res.family == "LightGBM"].sort_values("cv_mae").head(8).drop(columns=["family", "alpha"])
           .astype({k: type(v[0]) for k, v in GRID.items()}).reset_index(drop=True))
    lines = [
        "# M2 improvement pass (auto-generated by `python -m scout.ml.tune`)", "",
        f"Validation data only; the test years are never loaded. Commit `{git_commit()}`. "
        f"{len(configs)} LightGBM configs and {len(RIDGE_ALPHAS)} ridge alphas, each scored by rolling-origin CV "
        f"(fit on 2013..y-1, score y, for y = {CV_YEARS[0]}–{CV_YEARS[-1]}); the best of each family is then compared once on 2022.", "",
        f"**Picked:** LightGBM {lgb_cfg} · ridge alpha = {alpha:g}", "",
        "## Top LightGBM configs (mean CV MAE)", "", md_table(top.rename_axis("rank")), "",
        "## Ridge alphas (mean CV MAE)", "", md_table(res[res.family == "Ridge"][["alpha", "cv_mae"]].set_index("alpha")), "",
        "## Validation 2022", "", md_table(val_table), "",
        f"Tuned LightGBM minus tuned linear, MAE: {d:+.4f} (bootstrap 95% CI [{lo:+.4f}, {hi:+.4f}]).", "",
        "## Where does LightGBM beat linear? (pooled CV folds 2016–2021 + 2022, both tuned)", "",
        "`diff` = MAE(LightGBM) − MAE(linear); negative = LightGBM better. \"yes\"/\"no\" only when the 95% CI excludes 0.", "",
    ]
    for name, t in tables.items():
        lines += [f"### By {name}", "", md_table(t), ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
