import numpy as np
import pandas as pd

from scout.ml.intervals import conformal_margin, coverage_table


def test_conformal_margin_gives_nominal_coverage_on_exchangeable_data():
    rng = np.random.default_rng(0)
    y_cal, y_new = rng.normal(size=2000), rng.normal(size=20000)
    q_lo, q_hi = np.full(2000, -0.5), np.full(2000, 0.5)  # deliberately too narrow
    m = conformal_margin(y_cal, q_lo, q_hi, alpha=0.2)
    assert m > 0  # widened
    covered = ((y_new >= -0.5 - m) & (y_new <= 0.5 + m)).mean()
    assert 0.78 <= covered <= 0.82


def test_conformal_margin_can_shrink_too_wide_intervals():
    y = np.random.default_rng(1).normal(size=1000)
    assert conformal_margin(y, np.full(1000, -5.0), np.full(1000, 5.0)) < 0


def test_coverage_table():
    df = pd.DataFrame({"target": [0.0, 1.0, 2.0, 3.0], "g": ["a", "a", "b", "b"]})
    t = coverage_table(df, np.array([-1, 0, 0, 0]), np.array([1, 0.5, 3, 2]), by="g")
    assert t.loc["a", "coverage"] == 0.5 and t.loc["b", "coverage"] == 0.5
