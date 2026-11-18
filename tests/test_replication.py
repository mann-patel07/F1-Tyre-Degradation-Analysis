import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from replication import run_season  # noqa: E402

NAMES = ["races", "validation", "full_race_fits", "horizon", "summary", "sensitivity_train_fraction",
         "sensitivity_clean_air", "filter_counts", "stints"]


def _roundtrip(df):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return pd.read_csv(buf)


def test_run_season_reproduces_2025_results():
    laps = pd.read_csv(ROOT / "data/laps_2025.csv", dtype={"TrackStatus": str})
    races = pd.read_csv(ROOT / "data/races_2025.csv")
    res = run_season(laps, races)
    for k in NAMES:
        new, old = _roundtrip(res[k]), pd.read_csv(ROOT / f"results/{k}.csv")
        assert len(new) == len(old), k
        assert set(new.columns) == set(old.columns), k
        for c in old.columns:
            a, b = old[c], new[c]
            if pd.api.types.is_numeric_dtype(a) and not pd.api.types.is_bool_dtype(a):
                assert np.allclose(a.to_numpy(float), b.to_numpy(float), rtol=0, atol=1e-9, equal_nan=True), (k, c)
            else:
                assert (a.fillna("<NA>").astype(str) == b.fillna("<NA>").astype(str)).all(), (k, c)
