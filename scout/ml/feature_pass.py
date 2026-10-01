"""Pre-registered stats feature pass (docs/RESEARCH_LOG.md, 2026-10-01). Validation data only.

Protocol: B0 vs B0+P / +A / +D / +I / +ALL; LightGBM with the fixed tuned settings and ridge (alpha from
best_params.json); rolling-origin CV (fit 2013..y-1, score y, y = 2016-2021) plus validation 2022 (fit 2013-2021).
Decision rule (as pre-registered): a set helps if its mean CV MAE (LightGBM) beats B0 and the paired-bootstrap 95% CI of
MAE(set) - MAE(B0), pooled over CV folds + 2022, is entirely below 0. Winner: ALL if it helps and is best, else the
helping set with the lowest mean CV MAE, else B0.

Usage: uv run --env-file .env python -m scout.ml.feature_pass      -> reports/m3_stats_pass.md, MLflow run
"""
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from scout.data.raw import read_raw
from scout.data.snapshots import build_snapshots
from scout.ml.features import CATEGORICAL, NUMERIC, build_features
from scout.ml.stats_features import ALL_STATS, SETS, build_stats_features
from scout.ml.train import ROOT, TEST_YEARS, TRAIN_YEARS, VAL_YEAR, best_params, git_commit, mae_diff_ci, md_table

REPORT = ROOT / "reports" / "m3_stats_pass.md"
CV_YEARS = list(range(2016, 2022))
CANDIDATES = {"B0": [], **{k: v for k, v in SETS.items()}, "ALL": ALL_STATS}


def dataset() -> pd.DataFrame:
    raw = read_raw()
    s = build_snapshots(raw, years=TRAIN_YEARS + [VAL_YEAR])  # whole population: percentiles are within the year
    f = build_features(s, raw)
    st = build_stats_features(s, f, raw)
    df = pd.concat([s.drop(columns=[c for c in f.columns if c in s.columns]), f, st], axis=1)
    df = df[df.target.notna()]
    assert not df.year.isin(TEST_YEARS).any()
    return df


def lgbm(train, test, numeric):
    cols = numeric + CATEGORICAL
    x = lambda d: d[cols].astype({c: "category" for c in CATEGORICAL})
    params, _ = best_params()
    return lgb.LGBMRegressor(**params).fit(x(train), train.target).predict(x(test))


def ridge(train, test, numeric):
    _, alpha = best_params()
    m = make_pipeline(ColumnTransformer([
        ("num", make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), numeric),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL)]), Ridge(alpha=alpha))
    return m.fit(train, train.target).predict(test)


def evaluate(df):
    folds = [(y, df[df.year < y], df[df.year == y]) for y in CV_YEARS] + [(VAL_YEAR, df[df.year.isin(TRAIN_YEARS)], df[df.year == VAL_YEAR])]
    y_all = np.concatenate([ev.target.to_numpy() for _, _, ev in folds])
    preds, rows = {}, []
    for name, extra in CANDIDATES.items():
        numeric = NUMERIC + extra
        for model, fn in [("LightGBM", lgbm), ("Ridge", ridge)]:
            p = [fn(tr, ev, numeric) for _, tr, ev in folds]
            preds[(name, model)] = np.concatenate(p)
            maes = [np.abs(pi - ev.target.to_numpy()).mean() for pi, (_, _, ev) in zip(p, folds)]
            rows.append({"set": name, "model": model, "mean CV MAE (2016–2021)": float(np.mean(maes[:-1])),
                         "validation MAE (2022)": maes[-1], **{f"MAE {y}": m for (y, _, _), m in zip(folds, maes)}})
    table = pd.DataFrame(rows)
    comp = []
    b0 = table[(table.set == "B0") & (table.model == "LightGBM")]["mean CV MAE (2016–2021)"].iloc[0]
    for name in CANDIDATES:
        lg_row = table[(table.set == name) & (table.model == "LightGBM")].iloc[0]
        d, lo, hi = mae_diff_ci(y_all, preds[(name, "LightGBM")], preds[("B0", "LightGBM")])
        dl, lol, hil = mae_diff_ci(y_all, preds[(name, "LightGBM")], preds[(name, "Ridge")])
        helps = name != "B0" and lg_row["mean CV MAE (2016–2021)"] < b0 and hi < 0
        comp.append({"set": name, "mean CV MAE": lg_row["mean CV MAE (2016–2021)"], "val MAE 2022": lg_row["validation MAE (2022)"],
                     "vs B0 (pooled)": d, "vs B0 95% CI": f"[{lo:+.4f}, {hi:+.4f}]", "helps": "yes" if helps else "no",
                     "LightGBM − ridge": dl, "LightGBM − ridge 95% CI": f"[{lol:+.4f}, {hil:+.4f}]"})
    comp = pd.DataFrame(comp).set_index("set")
    helping = comp[comp.helps == "yes"]
    if "ALL" in helping.index and helping["mean CV MAE"].idxmin() == "ALL":
        winner = "ALL"
    elif len(helping):
        winner = helping["mean CV MAE"].idxmin()
    else:
        winner = "B0"
    return table, comp, winner, len(y_all)


def main() -> None:
    import mlflow
    from scout.ml.tracking import start_run
    df = dataset()
    coverage = df.groupby("year")[ALL_STATS].apply(lambda d: d.notna().mean()).round(3)
    with start_run("stats-feature-pass", tags={"stage": "m3a", "preregistered": "6f097e8"}):
        table, comp, winner, n = evaluate(df)
        mlflow.log_param("winner", winner)
        for name, r in comp.iterrows():
            mlflow.log_metric(f"cv_mae_{name}", float(r["mean CV MAE"]))
            mlflow.log_metric(f"val_mae_{name}", float(r["val MAE 2022"]))
    lines = [
        "# M3a stats feature pass (auto-generated by `python -m scout.ml.feature_pass`)", "",
        f"Pre-registered in docs/RESEARCH_LOG.md (commit `6f097e8`). Run at commit `{git_commit()}`. Validation data only "
        f"(2013–2022 snapshots; the test years are never loaded). Pooled CV folds 2016–2021 + validation 2022: n = {n:,}.", "",
        f"**Decision (pre-registered rule): new baseline = `{winner}`.**", "",
        "## LightGBM: each set vs B0 (decides) and vs ridge (reported)", "",
        "`vs B0` = MAE(set) − MAE(B0) on the pooled folds, with a paired-bootstrap 95% CI; negative = better.", "",
        md_table(comp, fmt="{:.4f}"), "",
        "## All MAEs (LightGBM and ridge, per fold)", "",
        md_table(table.set_index("set"), fmt="{:.4f}"), "",
        "## Feature coverage (share non-missing, by snapshot year)", "", md_table(coverage), "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT}; winner = {winner}")


if __name__ == "__main__":
    main()
