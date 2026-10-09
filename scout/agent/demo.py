"""Demo snapshot as of 2026-06-12, the last valuation date in the data (docs/SPEC.md): population, features and model
output (prediction, 80% interval, top SHAP factors), precomputed into `demo_players` so the API and agent only read.

The model was trained on 1-September snapshots; a June snapshot is a demo, not a validated use (the tools say so).

Usage: uv run --env-file .env python -m scout.agent.demo
"""
import pandas as pd
from psycopg import sql
from psycopg.types.json import Jsonb

from scout.data.manifest import RAW, ROOT
from scout.data.raw import read_raw
from scout.data.snapshots import build_snapshots
from scout.ml.features import build_features
from scout.ml.model import _py, explain, load_run
from scout.text.linker import fold

DEMO_AS_OF = pd.Timestamp("2026-06-12")


def build(raw: dict, run: dict) -> pd.DataFrame:
    s = build_snapshots(raw, years=[DEMO_AS_OF.year], with_target=False, as_of=DEMO_AS_OF)
    X = build_features(s, raw)
    out = explain(X, run["model"], top=5, interval=run["interval"])
    clubs = pd.read_csv(RAW / "clubs.csv", usecols=["club_id", "name"]).set_index("club_id").name
    names = raw["players"].set_index("player_id").name
    return pd.DataFrame({
        "player_id": s.player_id.astype(int), "name": s.player_id.map(names),
        "name_search": s.player_id.map(names).map(fold), "as_of": DEMO_AS_OF.date(),
        "club": s.club_id.map(clubs), "league": s.league, "position": X.position, "sub_position": X.sub_position,
        "age": X.age.round(1), "value_eur": s.value_now.astype("int64"), "value_date": s.value_now_date.dt.date,
        "predicted_log_change": [e["predicted_log_change"] for e in out],
        "interval_low_log": [e.get("interval_80", {}).get("low_log_change") for e in out],
        "interval_high_log": [e.get("interval_80", {}).get("high_log_change") for e in out],
        "factors": [e["factors"] for e in out], "model_run_id": run["run_id"],
    })


def main() -> None:
    from scout.text import store
    df = build(read_raw(), load_run())
    with store.connect() as conn:
        conn.execute("DROP TABLE IF EXISTS demo_players")  # derived data, rebuilt from scratch
        conn.execute((ROOT / "db" / "agent.sql").read_text(encoding="utf-8"))
        cols = list(df.columns)
        insert = sql.SQL("INSERT INTO demo_players ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, cols)), sql.SQL(", ").join(sql.Placeholder() * len(cols)))
        with conn.cursor() as cur:
            cur.executemany(insert, [tuple(Jsonb(v) if c == "factors" else _py(v) for c, v in zip(cols, r))
                                     for r in df.itertuples(index=False)])
        conn.commit()
    print(f"demo_players: {len(df):,} players as of {DEMO_AS_OF.date()} (model run {df.model_run_id.iloc[0]})")


if __name__ == "__main__":
    main()
