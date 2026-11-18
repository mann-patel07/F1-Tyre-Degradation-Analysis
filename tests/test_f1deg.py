import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as C  # noqa: E402
import f1deg as F  # noqa: E402

RATES = {"HARD": 0.05, "MEDIUM": 0.08, "SOFT": 0.12}


def mk(rows):
    base = dict(Driver="AAA", LapNumber=5, LapTime=90.0, Stint=1, Compound="MEDIUM",
                TyreLife=3, TrackStatus="1", IsAccurate=True,
                is_pit_in_lap=False, is_pit_out_lap=False, lap_end_s=0.0)
    return pd.DataFrame([{**base, **r} for r in rows])


def simulate(deg=RATES, lap_coef=-0.06, noise=0.2, seed=1, n_drivers=20, laps=57):
    rng = np.random.default_rng(seed)
    comps = ["SOFT", "MEDIUM", "HARD"]
    drv_off = rng.normal(0, 0.4, n_drivers)
    comp_off = {"SOFT": -0.6, "MEDIUM": 0.0, "HARD": 0.5}
    rows = []
    for d in range(n_drivers):
        p1 = int(rng.integers(12, 30))
        p2 = int(rng.integers(p1 + 10, 48)) if d % 2 == 0 else None
        bounds = [0, p1] + ([p2] if p2 else []) + [laps]
        cs = [comps[int(rng.integers(0, 3))]]
        for _ in range(len(bounds) - 2):
            cs.append(comps[(comps.index(cs[-1]) + int(rng.integers(1, 3))) % 3])
        for s in range(len(bounds) - 1):
            for lap in range(bounds[s] + 1, bounds[s + 1] + 1):
                age = lap - bounds[s]
                t = (90 + drv_off[d] + comp_off[cs[s]] + deg[cs[s]] * age
                     + lap_coef * lap + rng.normal(0, noise))
                rows.append(dict(Driver=f"D{d:02d}", LapNumber=lap, LapTime=t, Stint=s + 1,
                                 Compound=cs[s], TyreLife=age, TrackStatus="1",
                                 IsAccurate=True, is_pit_in_lap=lap == bounds[s + 1] and s < len(bounds) - 2,
                                 is_pit_out_lap=lap == bounds[s] + 1 and s > 0,
                                 lap_end_s=lap * 90.0 + d * 0.5))
    return pd.DataFrame(rows)


def test_pit_laps_removed():
    raw = mk([{"LapNumber": 3}, {"LapNumber": 4, "is_pit_in_lap": True},
              {"LapNumber": 5, "is_pit_out_lap": True}])
    c, _, _ = F.clean_laps(raw)
    assert list(c["LapNumber"]) == [3]


def test_track_status():
    raw = mk([{"LapNumber": 3 + i, "TrackStatus": s} for i, s in enumerate(["1", "2", "4", "12", "6"])])
    c, _, _ = F.clean_laps(raw)
    assert list(c["TrackStatus"]) == ["1"]


def test_other_filters():
    raw = mk([{"LapNumber": 1}, {"LapNumber": 3, "IsAccurate": False},
              {"LapNumber": 4, "LapTime": np.nan}, {"LapNumber": 5, "Compound": "WET"},
              {"LapNumber": 6, "Compound": "INTERMEDIATE"}, {"LapNumber": 7}])
    c, _, _ = F.clean_laps(raw)
    assert list(c["LapNumber"]) == [7]


def test_slow_lap_rule():
    raw = mk([{"LapNumber": 3, "LapTime": 100.0},
              {"LapNumber": 4, "LapTime": C.SLOW_LAP_FACTOR * 100.0},
              {"LapNumber": 5, "LapTime": C.SLOW_LAP_FACTOR * 100.0 + 0.01},
              {"LapNumber": 6, "LapTime": 80.0, "is_pit_out_lap": True}])
    c, counts, thr = F.clean_laps(raw)
    assert sorted(c["LapNumber"]) == [3, 4]
    assert thr == pytest.approx(107.0)
    assert counts["s7_not_slow"] == 2


def test_wet_flag():
    assert F.is_wet_race(mk([{"Compound": "INTERMEDIATE"}, {}]))
    assert not F.is_wet_race(mk([{}, {"Compound": "SOFT"}]))


def test_gap_ahead():
    raw = mk([{"Driver": "A", "lap_end_s": 100.0}, {"Driver": "B", "lap_end_s": 102.5},
              {"Driver": "B", "lap_end_s": 190.0}, {"Driver": "B", "lap_end_s": 200.0},
              {"Driver": "A", "lap_end_s": 205.0}])
    g = F.add_gap_ahead(raw)["gap_ahead_s"].to_numpy()
    assert np.isnan(g[0])
    assert g[1] == pytest.approx(2.5)
    assert g[2] == pytest.approx(90.0)   # latest other-driver crossing is A at 100, not own 102.5
    assert g[3] == pytest.approx(100.0)  # B twice in a row, no other car between
    assert g[4] == pytest.approx(5.0)


def test_split_cutoff_and_overlap():
    raw = simulate()
    raw = raw[raw["LapNumber"] <= 57]
    out = F.forecast_race(raw)
    assert out["cutoff"] == 34 == math.floor(C.TRAIN_FRACTION * 57)
    assert out["train"]["LapNumber"].max() <= 34
    assert out["test"]["LapNumber"].min() > 34
    assert not set(out["train"].index) & set(out["test"].index)


def test_no_leakage():
    raw = simulate()
    a = F.forecast_race(raw)
    r2 = raw.copy()
    r2.loc[r2["LapNumber"] > 34, "LapTime"] *= 1.03
    b = F.forecast_race(r2)
    assert a["threshold"] == b["threshold"]
    for m in F.MODELS:
        assert np.allclose(a[f"params_{m}"].to_numpy(), b[f"params_{m}"].to_numpy())


def test_recovery():
    raw = simulate()
    clean, _, _ = F.clean_laps(raw)
    res = F.fit_model(clean, "M1")
    rates = F.deg_rates(res)
    assert set(rates) == set(clean["Compound"].unique())
    for c, r in rates.items():
        assert abs(r - RATES[c]) < 0.02
    assert abs(res.params["LapNumber"] - (-0.06)) < 0.01


def test_null_case():
    raw = simulate(deg={"HARD": 0.0, "MEDIUM": 0.0, "SOFT": 0.0})
    out = F.forecast_race(raw)
    assert out["eligible"]
    assert -0.02 <= out["MAE_M0"] - out["MAE_M1"] <= 0.02


def test_unseen_driver_and_dropped_compound():
    raw = simulate()
    extra = mk([{"Driver": "NEW", "LapNumber": 40 + i, "LapTime": 88.0, "TyreLife": 5 + i,
                 "lap_end_s": 5000.0 + i} for i in range(5)])
    rare = mk([{"Driver": "D00", "LapNumber": 50 + i, "LapTime": 88.0, "Compound": "SOFT",
                "TyreLife": 70 + i, "lap_end_s": 6000.0 + i} for i in range(3)]
              + [{"Driver": "D00", "LapNumber": 5 + i, "LapTime": 88.0, "Compound": "SOFT",
                  "TyreLife": 60 + i, "lap_end_s": 7000.0 + i} for i in range(5)])
    raw = raw[raw["Compound"] != "SOFT"]
    raw = pd.concat([raw, extra, rare], ignore_index=True)
    out = F.forecast_race(raw)
    assert out["removed_test_driver"] >= 5
    assert "SOFT" in out["dropped_compounds"]
    assert out["removed_test_compound"] == 3
    assert out["eligible"]


def test_confound():
    lap = np.arange(5, 25)
    df = pd.DataFrame({"TyreLife": lap - 4, "lap_s": 90 + 0.05 * (lap - 4) - 0.06 * lap})
    assert F.naive_slope(df) == pytest.approx(-0.01, abs=1e-9)


def test_minisectors():
    lap_s = 90.0
    rel = np.linspace(0, 1, 500)
    t = rel * 88.0
    raw = F.minisector_times(t, rel)
    assert len(raw) == C.N_MINISECTORS
    assert np.allclose(raw, raw[0])
    scaled = F.rescale_to_lap(raw, lap_s)
    assert scaled.sum() == pytest.approx(lap_s)
    assert np.allclose(scaled, lap_s / C.N_MINISECTORS)


def test_bootstrap():
    x = np.array([0.1, -0.2, 0.3, 0.05, 0.4])
    assert F.bootstrap_mean_ci(x, 500, 7) == F.bootstrap_mean_ci(x, 500, 7)
    lo, hi = F.bootstrap_mean_ci(np.full(8, 0.25), 500, 3)
    assert lo == pytest.approx(0.25) and hi == pytest.approx(0.25)


def test_metrics():
    actual = np.array([90.0, 91.0, 92.0, 93.0, 94.0])
    pred = np.array([91.0, 90.0, 92.0, 95.0, 94.0])
    err = pred - actual  # 1, -1, 0, 2, 0
    assert F.mae(err) == pytest.approx(0.8)
    assert F.rmse(err) == pytest.approx(math.sqrt(6 / 5))
    assert F.bias(pred, actual) == pytest.approx(0.4)
