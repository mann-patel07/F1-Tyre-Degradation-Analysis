"""Where degradation costs time, season-wide. Reads saved files only. Never imports fastf1."""
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

import config as cfg
import f1deg as F

N = cfg.N_MINISECTORS


def classify(rel: np.ndarray, throttle: np.ndarray, brake: np.ndarray, n: int = N) -> Tuple[List[str], List[str]]:
    """class and class3 per mini-sector from reference lap samples."""
    idx = np.minimum((np.asarray(rel) * n).astype(int), n - 1)
    thr, brk = np.asarray(throttle, dtype=float), np.asarray(brake).astype(bool)
    c2, c3 = [], []
    for k in range(n):
        sel = idx == k
        if not sel.any():
            c2.append("CORNER")
            c3.append("CORNER_NO_BRAKE")
            continue
        low = thr[sel].min() < cfg.STRAIGHT_THROTTLE_MIN
        c2.append("CORNER" if low else "STRAIGHT")
        c3.append("BRAKING" if brk[sel].any() else ("CORNER_NO_BRAKE" if low else "STRAIGHT"))
    return c2, c3


def density(rate: float, time: float) -> Optional[float]:
    """Fitted degradation per second of lap time; undefined if no time is spent in the class."""
    return None if (time is None or time <= 0) else rate / time


def density_difference(corner_rate: float, corner_time: float, straight_rate: float, straight_time: float) -> Optional[float]:
    """G = corner density minus straight density; undefined if either class is empty."""
    dc, ds = density(corner_rate, corner_time), density(straight_rate, straight_time)
    return None if (dc is None or ds is None) else dc - ds


def primary_compound(ms_df: pd.DataFrame) -> str:
    """Compound with the most kept laps (tie: alphabetical first)."""
    cnt = ms_df["Compound"].value_counts()
    top = cnt.max()
    return sorted(c for c in cnt.index if cnt[c] == top)[0]


def linearity(ms_df: pd.DataFrame, tol: float = 1e-6) -> pd.DataFrame:
    """Compare the sum of mini-sector rates with the lap-time fit, per compound and LapNumber."""
    lap = F.fit_model(ms_df, "M1")
    rates = F.deg_rates(lap)
    sums = {c: 0.0 for c in rates}
    lap_sum = 0.0
    for k in range(N):
        res = F.fit_model(ms_df, "M1", response=f"ms_{k}")
        r = F.deg_rates(res)
        for c in sums:
            sums[c] += r[c]
        lap_sum += float(res.params["LapNumber"])
    rows = [{"term": c, "sum_of_minisectors": sums[c], "lap_time_fit": rates[c]} for c in sorted(rates)]
    rows.append({"term": "LapNumber", "sum_of_minisectors": lap_sum, "lap_time_fit": float(lap.params["LapNumber"])})
    df = pd.DataFrame(rows)
    df["abs_difference"] = (df["sum_of_minisectors"] - df["lap_time_fit"]).abs()
    assert (df["abs_difference"] < tol).all(), df
    return df


def fit_race(ms_raw: pd.DataFrame, ref: pd.DataFrame):
    """Mini-sector fits and per-compound class rates for one race."""
    ms_df, _ = F.apply_compound_minimum(ms_raw)
    lin = linearity(ms_df)
    c2, c3 = classify(ref["rel"].to_numpy(), ref["Throttle"].to_numpy(), ref["Brake"].to_numpy())
    comps = sorted(ms_df["Compound"].unique())
    fit_rows = []
    for k in range(N):
        res = F.fit_model(ms_df, "M1", response=f"ms_{k}")
        r = F.deg_rates(res)
        row = {"minisector": k, "lap_coef": float(res.params["LapNumber"]), "mean_time_s": float(ms_df[f"ms_{k}"].mean())}
        for c in comps:
            row[f"deg_rate_{c}"] = r[c]
        fit_rows.append(row)
    fits = pd.DataFrame(fit_rows)
    refrow = ms_df.loc[ms_df["lap_s"].idxmin()]
    ref_times = np.array([refrow[f"ms_{k}"] for k in range(N)])
    c2a, c3a = np.array(c2), np.array(c3)
    nlaps = ms_df["Compound"].value_counts()
    prim = primary_compound(ms_df)
    rows = []
    for c in comps:
        rates = fits[f"deg_rate_{c}"].to_numpy()
        row = {"compound": c, "kept_laps": int(nlaps[c]), "is_primary": c == prim, "total_rate": float(rates.sum())}
        for name, lab in (("corner", "CORNER"), ("straight", "STRAIGHT")):
            m = c2a == lab
            row[f"{name}_rate"] = float(rates[m].sum())
            row[f"{name}_time"] = float(ref_times[m].sum())
            row[f"n_{name}"] = int(m.sum())
        row["G"] = density_difference(row["corner_rate"], row["corner_time"], row["straight_rate"], row["straight_time"])
        for lab in ("BRAKING", "CORNER_NO_BRAKE", "STRAIGHT"):
            m = c3a == lab
            row[f"rate_{lab}"] = float(rates[m].sum())
            row[f"time_{lab}"] = float(ref_times[m].sum())
            row[f"density_{lab}"] = density(row[f"rate_{lab}"], row[f"time_{lab}"]) if m.any() else None
        rows.append(row)
    return fits, pd.DataFrame(rows), lin


def run_fit(root: Path) -> None:
    """Fit every saved race and write results/telemetry_season/."""
    root = Path(root)
    out = root / "results/telemetry_season"
    out.mkdir(parents=True, exist_ok=True)
    r25 = pd.read_csv(root / "data/races_2025.csv").set_index("Round")
    files = sorted((root / "data/minisectors_2025").glob("*.csv"))
    race_rows, lin_rows = [], []
    for f in files:
        rnd = int(f.stem)
        ms_raw = pd.read_csv(f)
        ref = pd.read_csv(root / "data/reference_laps_2025" / f"{f.stem}.csv")
        fits, rc, lin = fit_race(ms_raw, ref)
        if rnd == int(r25[r25["EventName"] == cfg.CASE_STUDY_EVENT].index[0]):
            old = pd.read_csv(root / "results/minisector_fits.csv")
            new_ms = pd.read_csv(root / "data/bahrain_minisectors.csv")
            assert len(ms_raw) == len(new_ms), "Bahrain row count differs"
            cols = [c for c in new_ms.columns if c.startswith("ms_")]
            assert np.allclose(ms_raw[cols].to_numpy(), new_ms[cols].to_numpy(), atol=1e-6)
            for c in [c for c in old.columns if c != "minisector"]:
                assert np.allclose(fits[c].to_numpy(), old[c].to_numpy(), atol=1e-6, rtol=0), ("Bahrain fit differs", c)
        fits.to_csv(out / f"minisector_fits_{f.stem}.csv", index=False)
        rc.insert(0, "event", r25.loc[rnd, "EventName"])
        rc.insert(0, "round", rnd)
        race_rows.append(rc)
        lin.insert(0, "round", rnd)
        lin_rows.append(lin)
    rc = pd.concat(race_rows, ignore_index=True)
    rc.to_csv(out / "race_compound.csv", index=False)
    pd.concat(lin_rows, ignore_index=True).to_csv(out / "linearity.csv", index=False)
    prim = rc[rc["is_primary"]]
    srows = []
    left = prim[prim["G"].isna()]
    used = prim[prim["G"].notna()]
    if len(used):
        v = used["G"].to_numpy()
        lo, hi = F.bootstrap_mean_ci(v)
        srows.append({"metric": "T1", "value": float(v.mean()), "lo": lo, "hi": hi, "n": len(v), "note": ""})
        srows.append({"metric": "races_used", "value": len(v), "lo": None, "hi": None, "n": len(v), "note": ""})
        srows.append({"metric": "races_G_positive", "value": int((v > 0).sum()), "lo": None, "hi": None, "n": len(v), "note": ""})
    for _, r in left.iterrows():
        srows.append({"metric": "left_out", "value": int(r["round"]), "lo": None, "hi": None, "n": 0,
                      "note": "G undefined: no corner or no straight mini-sector"})
    for lab in ("BRAKING", "CORNER_NO_BRAKE", "STRAIGHT"):
        v = prim[f"density_{lab}"].dropna().to_numpy(dtype=float)
        if len(v):
            lo, hi = F.bootstrap_mean_ci(v)
            srows.append({"metric": f"density_{lab}", "value": float(v.mean()), "lo": lo, "hi": hi, "n": len(v),
                          "note": "mean over races, primary compound, seconds of degradation per second of lap time"})
    pd.DataFrame(srows).to_csv(out / "summary.csv", index=False)
    print("races fitted:", len(files))
