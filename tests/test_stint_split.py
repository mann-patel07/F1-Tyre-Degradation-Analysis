"""Tests for stint_split.py."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import stint_split as ss  # noqa: E402


def synthetic():
    train = pd.DataFrame({"Driver": ["AAA", "AAA", "BBB", "CCC"], "Stint": [1.0, 1.0, 1.0, 2.0]})
    test = pd.DataFrame({"Driver": ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC", "DDD"],
                         "Stint": [1.0, 2.0, 1.0, 2.0, 2.0, 3.0, 1.0],
                         "lap_s": 90.0, "pred_M0": 91.0, "pred_M1": 90.5, "pred_M2": 90.0})
    return train, test


def test_continuing_mask_marks_exactly_the_laps_whose_driver_and_stint_are_in_training():
    train, test = synthetic()
    assert ss.continuing_mask(test, train).tolist() == [True, False, True, False, True, False, False]


def test_the_two_groups_cover_every_test_lap_once():
    train, test = synthetic()
    mask = ss.continuing_mask(test, train)
    a, b = ss.group_maes(test, mask), ss.group_maes(test, ~mask)
    assert a["n"] + b["n"] == len(test)
    assert a["n"] == mask.sum() and b["n"] == (~mask).sum()


def test_a_group_with_fewer_than_20_laps_gives_nan_and_is_left_out_of_the_mean():
    train, test = synthetic()
    row = ss.group_row(test, ss.continuing_mask(test, train))
    assert np.isnan(row["D1"]) and np.isnan(row["D2"]) and row["n"] == 3
    enough = pd.concat([test] * 8, ignore_index=True)
    row = ss.group_row(enough, np.ones(len(enough), dtype=bool))
    assert row["D1"] == pytest.approx(0.5) and row["D2"] == pytest.approx(0.5)
    df = pd.DataFrame({"n_continuing": [30, 30], "n_new": [5, 25],
                       "D1_continuing": [0.1, 0.3], "D2_continuing": [0.0, 0.0],
                       "D1_new": [np.nan, 0.5], "D2_new": [np.nan, 0.1]})
    s = pd.DataFrame(ss.summarize(df, "x")).set_index(["group", "metric"])["value"]
    assert s["new", "races"] == 1 and s["new", "D1"] == pytest.approx(0.5)
    assert s["continuing", "races"] == 2 and s["continuing", "D1"] == pytest.approx(0.2)


def test_weighted_group_mae_equals_the_race_mae_in_the_first_version():
    base, o = ss.eligible_races(2025)[0]
    val = pd.read_csv(ROOT / "results/validation.csv")
    row = val[val["Round"] == base["Round"]].iloc[0]
    t = o["test"]
    mask = ss.continuing_mask(t, o["train"])
    a, b = ss.group_maes(t, mask), ss.group_maes(t, ~mask)
    for m in ("M0", "M1", "M2"):
        weighted = (a["n"] * a[f"MAE_{m}"] + b["n"] * b[f"MAE_{m}"]) / (a["n"] + b["n"])
        assert weighted == pytest.approx(row[f"MAE_{m}"], abs=1e-9)


def test_eligible_rounds_for_2025_equal_those_in_the_first_version():
    found = sorted(b["Round"] for b, _ in ss.eligible_races(2025))
    val = pd.read_csv(ROOT / "results/validation.csv")
    assert found == sorted(val["Round"].astype(int))
