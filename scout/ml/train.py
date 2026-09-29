"""Train and evaluate the 12-month value-change model; writes models/lgbm.txt and reports/results.md.

Usage: uv run python -m scout.ml.train
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from scout.data.target import build_targets
from scout.ml.features import CATEGORICAL, FEATURES, FIRST_SNAPSHOT, NUMERIC, RAW, build_features, in_scope, read_raw
from scout.ml.model import MODEL_PATH, explain, to_model_input

REPORT = Path(__file__).resolve().parents[2] / "reports" / "results.md"
VAL_START = pd.Timestamp("2023-07-01")   # season 2023-24
TEST_START = pd.Timestamp("2024-07-01")  # season 2024-25 onward
LGB_PARAMS = dict(n_estimators=3000, learning_rate=0.03, num_leaves=63, min_child_samples=200,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)


def split(df: pd.DataFrame):
    """Time-based split on snapshot date. Training rows whose target resolves on/after VAL_START are
    dropped (purged), so no training label contains price moves from the validation/test period."""
    train = df[(df.date < VAL_START) & (df.future_date < VAL_START)]
    val = df[(df.date >= VAL_START) & (df.date < TEST_START)]
    test = df[df.date >= TEST_START]
    return train, val, test


def metrics(y, p) -> dict:
    y, p = np.asarray(y), np.asarray(p)
    err, moved = p - y, y != 0
    # direction: sign of prediction vs sign of actual, on snapshots whose value actually changed
    direction = np.nan if np.all(p == 0) else (np.sign(p[moved]) == np.sign(y[moved])).mean()
    return {"MAE": np.abs(err).mean(), "RMSE": np.sqrt((err ** 2).mean()), "Direction acc.": direction}


def linear_model():
    return make_pipeline(
        ColumnTransformer([
            ("num", make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ]),
        Ridge(alpha=1.0),
    )


def md_table(df: pd.DataFrame, fmt="{:.3f}") -> str:
    cell = lambda x: fmt.format(x) if isinstance(x, float) and not np.isnan(x) else ("n/a" if isinstance(x, float) else str(x))
    rows = [[str(df.index.name or "")] + list(map(str, df.columns))]
    rows += [[str(i)] + [cell(x) for x in r] for i, r in zip(df.index, df.itertuples(index=False))]
    return "\n".join("| " + " | ".join(r) + " |" for r in [rows[0], ["---"] * len(rows[0]), *rows[1:]])


def main() -> None:
    raw = read_raw()
    targets = build_targets(raw["valuations"])
    feats = build_features(targets, raw)
    df = pd.concat([targets, feats], axis=1)[in_scope(targets, feats)]
    train, val, test = split(df)
    print(f"in scope: {len(df):,}  train: {len(train):,}  val: {len(val):,}  test: {len(test):,}")

    age_curve = train.groupby(train.age.round().clip(16, 38)).target.mean()
    age_only = lambda d: d.age.round().clip(16, 38).map(age_curve).fillna(train.target.mean()).to_numpy()
    linear = linear_model().fit(train[FEATURES], train.target)
    gbm = lgb.LGBMRegressor(**LGB_PARAMS).fit(
        to_model_input(train), train.target, eval_X=(to_model_input(val),), eval_y=(val.target,),
        callbacks=[lgb.early_stopping(100, verbose=False)])
    print(f"LightGBM best iteration: {gbm.best_iteration_}")

    predictors = {
        "No change": lambda d: np.zeros(len(d)),
        "Age-only (mean by age)": age_only,
        "Linear (ridge)": lambda d: linear.predict(d[FEATURES]),
        "LightGBM": lambda d: gbm.predict(to_model_input(d)),
    }
    results = {name: pd.DataFrame({s: metrics(d.target, f(d)) for s, d in [("val", val), ("test", test)]}).T
               for name, f in predictors.items()}
    table = pd.concat(results).unstack(0).swaplevel(axis=1)  # rows: split; cols: (model, metric)
    for s in ["val", "test"]:
        print(f"\n{s}:\n" + table.loc[s].unstack(0).round(3).to_string())

    # Model used by the API: same settings, refit on every labelled in-scope snapshot
    serving = lgb.LGBMRegressor(**{**LGB_PARAMS, "n_estimators": gbm.best_iteration_}).fit(to_model_input(df), df.target)
    MODEL_PATH.parent.mkdir(exist_ok=True)
    serving.booster_.save_model(str(MODEL_PATH))
    print(f"\nsaved {MODEL_PATH}")

    # SHAP on the evaluation model (trained without test data)
    contrib = gbm.predict(to_model_input(test), pred_contrib=True)[:, :-1]
    importance = pd.DataFrame({"mean abs SHAP": np.abs(contrib).mean(0)}, index=pd.Index(FEATURES, name="feature"))
    importance = importance.sort_values("mean abs SHAP", ascending=False)

    names = pd.read_csv(RAW / "players.csv", usecols=["player_id", "name"]).set_index("player_id").name
    clubs = pd.read_csv(RAW / "player_valuations.csv", usecols=["player_id", "date", "current_club_name"], parse_dates=["date"])
    pool = test.assign(pred=predictors["LightGBM"](test)).merge(clubs, on=["player_id", "date"])
    pool = pool[pool.value_now >= 5_000_000].assign(err=lambda d: d.pred - d.target)
    hits = pool[(np.sign(pool.pred) == np.sign(pool.target)) & (pool.err.abs() < 0.1)]
    hits = hits.sort_values("target", key=np.abs, ascending=False).drop_duplicates("player_id").head(3)
    misses = pool.sort_values("err", key=np.abs, ascending=False).drop_duplicates("player_id").head(2)
    cases = pd.concat([hits.assign(kind="hit"), misses.assign(kind="miss")])
    expl = explain(cases, gbm.booster_)

    lines = [
        "# Phase 2 results (auto-generated by `python -m scout.ml.train`)", "",
        f"Scope: snapshots from {FIRST_SNAPSHOT:%Y-%m-%d} whose club was in a core league at the snapshot date. "
        f"In scope: {len(df):,}. Train (snapshot and target both before {VAL_START:%Y-%m-%d}): {len(train):,}. "
        f"Val ({VAL_START:%Y-%m-%d} to {TEST_START:%Y-%m-%d}): {len(val):,}. Test (from {TEST_START:%Y-%m-%d}): {len(test):,}.",
        f"LightGBM early-stopped at {gbm.best_iteration_} trees.", "",
        "Direction acc. = share of snapshots whose value changed where sign(prediction) == sign(actual); "
        "n/a for no-change, which never predicts a direction.", "",
    ]
    for s in ["val", "test"]:
        lines += [f"## Metrics: {s}", "", md_table(table.loc[s].unstack(0).rename_axis("model")), ""]
    lines += ["## Feature importance (mean |SHAP|, test set)", "", md_table(importance), "", "## Case studies (test set, value ≥ €5m)", ""]
    for (_, c), e in zip(cases.iterrows(), expl):
        factors = "; ".join(f"`{f['feature']}` = {f['value']:.3g} ({f['shap']:+.2f})" if isinstance(f["value"], float)
                            else f"`{f['feature']}` = {f['value'] if f['value'] is not None else 'missing'} ({f['shap']:+.2f})" for f in e["factors"][:4])
        lines += [
            f"### {c.kind.upper()}: {names.get(c.player_id, c.player_id)}, {c.current_club_name} ({c.league}), {c.date:%Y-%m-%d}",
            f"- Age {c.age:.1f}, {c.sub_position}. Value €{c.value_now / 1e6:.1f}m → €{c.value_future / 1e6:.1f}m on {c.future_date:%Y-%m-%d}",
            f"- Actual log change {c.target:+.2f} ({np.expm1(c.target):+.0%}); predicted {c.pred:+.2f} ({np.expm1(c.pred):+.0%})",
            f"- Top factors (SHAP, log-change units; base value {e['base_value']:+.2f}): {factors}", "",
        ]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
