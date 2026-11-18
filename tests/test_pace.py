import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pace as P  # noqa: E402


def simulate(seed=3, n_drivers=12, laps=57, noise=0.1):
    rng = np.random.default_rng(seed)
    comps = ["SOFT", "MEDIUM", "HARD"]
    off = rng.normal(0, 0.5, n_drivers)
    rates = {"SOFT": 0.12, "MEDIUM": 0.08, "HARD": 0.05}
    rows = []
    for d in range(n_drivers):
        p1 = int(rng.integers(12, 30))
        p2 = int(rng.integers(p1 + 10, 48)) if d % 2 == 0 else None
        b = [0, p1] + ([p2] if p2 else []) + [laps]
        cs = [comps[int(rng.integers(0, 3))]]
        for _ in range(len(b) - 2):
            cs.append(comps[(comps.index(cs[-1]) + int(rng.integers(1, 3))) % 3])
        for s in range(len(b) - 1):
            for lap in range(b[s] + 1, b[s + 1] + 1):
                age = lap - b[s]
                t = 90 + off[d] + rates[cs[s]] * age - 0.06 * lap + rng.normal(0, noise)
                rows.append(dict(Driver=f"D{d:02d}", Team=f"T{d // 2}", LapNumber=lap, lap_s=t, Stint=s + 1,
                                 Compound=cs[s], TyreLife=age))
    return pd.DataFrame(rows), off


def test_recovered_pace_matches_centred_offsets():
    df, off = simulate()
    res = P.race_pace(df)
    tab = res["drivers"].set_index("driver")
    true = off - off.mean()
    for d in range(len(off)):
        assert abs(tab.loc[f"D{d:02d}", "pace"] - true[d]) < 0.05
    assert abs(tab["pace"].mean()) < 1e-9


def test_reference_driver_effect_zero():
    df, _ = simulate()
    tab = P.race_pace(df)["drivers"].set_index("driver")
    assert tab.loc["D00", "effect"] == 0.0


def test_short_drivers_dropped_before_centring():
    df, _ = simulate()
    short = df[df["Driver"] == "D03"].head(10)
    df2 = pd.concat([df[df["Driver"] != "D03"], short])
    tab = P.race_pace(df2)["drivers"].set_index("driver")
    assert not tab.loc["D03", "kept"] and np.isnan(tab.loc["D03", "pace"])
    kept = tab[tab["kept"]]
    assert abs(kept["pace"].mean()) < 1e-9


def test_team_pace_is_mean_of_drivers():
    drivers = pd.DataFrame({"driver": ["A", "B", "C"], "team": ["X", "X", "Y"], "pace": [-0.2, 0.4, 0.1],
                            "kept": [True, True, True]})
    t = P.team_pace(drivers).set_index("team")
    assert abs(t.loc["X", "team_pace"] - 0.1) < 1e-12 and t.loc["Y", "team_pace"] == 0.1


def test_teammate_difference_sign_and_count():
    rows = []
    for rnd in range(1, 7):
        rows.append(dict(round=rnd, driver="AAA", team="X", pace=-0.2, kept=True))
        rows.append(dict(round=rnd, driver="BBB", team="X", pace=0.1 if rnd < 6 else -0.5, kept=True))
    t = P.teammate_table(pd.DataFrame(rows))
    r = t.iloc[0]
    assert r["races"] == 6 and r["driver_a"] == "AAA"
    assert abs(r["mean_diff"] - np.mean([-0.3] * 5 + [0.3])) < 1e-12
    assert r["a_faster"] == 5


def test_development_slope_hand_series():
    tr = pd.DataFrame({"team": "X", "round": np.arange(1, 11), "team_pace": 0.5 - 0.05 * np.arange(1, 11)})
    d = P.development(tr).iloc[0]
    assert abs(d["slope"] + 0.05) < 1e-12 and d["lo"] <= d["slope"] <= d["hi"]


def test_compound_comparison_formula():
    out = P.compound_diffs({"HARD": 0.0, "MEDIUM": -0.3, "SOFT": -0.6}, {"HARD": 0.04, "MEDIUM": 0.06, "SOFT": 0.10}, age=5)
    assert out["HARD-MEDIUM"] == pytest.approx(0.3 + 5 * (0.04 - 0.06))
    assert out["MEDIUM-SOFT"] == pytest.approx(0.3 + 5 * (0.06 - 0.10))
    assert out["HARD-SOFT"] == pytest.approx(0.6 + 5 * (0.04 - 0.10))
