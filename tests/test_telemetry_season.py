import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import telemetry_season as TS  # noqa: E402
import config as cfg  # noqa: E402

N = cfg.N_MINISECTORS


def test_class3_rule():
    rel = np.repeat((np.arange(N) + 0.5) / N, 4)
    thr = np.full(len(rel), 100.0)
    brk = np.zeros(len(rel), dtype=bool)
    thr[rel * N < 1] = 60.0            # sector 0: low throttle, no brake -> CORNER_NO_BRAKE
    brk[(rel * N >= 1) & (rel * N < 2)] = True   # sector 1: brake -> BRAKING
    thr[(rel * N >= 1) & (rel * N < 2)] = 40.0
    brk[(rel * N >= 2) & (rel * N < 3)] = True   # sector 2: brake with throttle 100 -> BRAKING
    keep = rel * N < 24
    c2, c3 = TS.classify(rel[keep], thr[keep], brk[keep])   # sector 24 has no samples
    assert c3[0] == "CORNER_NO_BRAKE" and c3[1] == "BRAKING" and c3[2] == "BRAKING" and c3[5] == "STRAIGHT"
    assert c2[0] == "CORNER" and c2[2] == "STRAIGHT" and c2[5] == "STRAIGHT"
    assert c2[24] == "CORNER" and c3[24] == "CORNER_NO_BRAKE"


def test_density_difference_hand_numbers():
    assert TS.density_difference(0.06, 60.0, 0.02, 20.0) == pytest.approx(0.06 / 60 - 0.02 / 20)
    assert TS.density_difference(0.06, 60.0, 0.03, 20.0) == pytest.approx(0.001 - 0.0015)


def test_undefined_when_class_empty():
    assert TS.density_difference(0.06, 60.0, 0.0, 0.0) is None
    assert TS.density_difference(0.0, 0.0, 0.02, 20.0) is None


def test_primary_compound_most_laps_tie_alphabetical():
    df = pd.DataFrame({"Compound": ["MEDIUM"] * 5 + ["HARD"] * 3 + ["SOFT"] * 5})
    assert TS.primary_compound(df) == "MEDIUM"
    assert TS.primary_compound(pd.DataFrame({"Compound": ["SOFT", "HARD"]})) == "HARD"


def test_linearity_helper_synthetic():
    rng = np.random.default_rng(5)
    rows = []
    for d in range(8):
        p = int(rng.integers(12, 25))
        for lap in range(1, 41):
            comp = "MEDIUM" if lap <= p else "HARD"
            age = lap if lap <= p else lap - p
            parts = rng.normal(3.0, 0.05, N) + 0.002 * age
            rows.append({"Driver": f"D{d}", "LapNumber": lap, "Compound": comp, "TyreLife": age,
                         "lap_s": parts.sum(), **{f"ms_{k}": parts[k] for k in range(N)}})
    df = pd.DataFrame(rows)
    lin = TS.linearity(df)
    assert (lin["abs_difference"] < 1e-6).all() and set(lin["term"]) == {"HARD", "MEDIUM", "LapNumber"}
