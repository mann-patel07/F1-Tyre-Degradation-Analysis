"""Library for the F1 tyre degradation study. Pure functions, no printing."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

import config as cfg

RHS = {
    "M0": "C(Driver) + C(Compound) + LapNumber",
    "M1": "C(Driver) + C(Compound) + C(Compound):TyreLife + LapNumber",
    "M2": ("C(Driver) + C(Compound) + C(Compound):TyreLife"
           " + C(Compound):I(TyreLife**2) + LapNumber"),
}
MODELS = ["M0", "M1", "M2"]
STEP_NAMES = ["s1_laptime_notnull", "s2_lap_ge_2", "s3_no_pit", "s4_green",
              "s5_accurate", "s6_dry_compound_tyrelife", "s7_not_slow"]


def is_wet_race(laps: pd.DataFrame) -> bool:
    """True if any lap in the raw table was run on a wet-weather compound."""
    return bool(laps["Compound"].isin(cfg.WET_COMPOUNDS).any())


def add_gap_ahead(laps: pd.DataFrame) -> pd.DataFrame:
    """Add gap_ahead_s: time at the line behind the car physically ahead."""
    out = laps.copy()
    gap = np.full(len(out), np.nan)
    valid = out["lap_end_s"].notna().to_numpy()
    idx = np.flatnonzero(valid)
    t = out["lap_end_s"].to_numpy()[idx]
    drv = out["Driver"].to_numpy()[idx]
    order = np.argsort(t, kind="stable")
    ts, ds = t[order], drv[order]
    for k, i in enumerate(order):
        pos = int(np.searchsorted(ts, t[i], side="left")) - 1
        while pos >= 0 and ds[pos] == drv[i]:
            pos -= 1
        if pos >= 0:
            gap[idx[i]] = t[i] - ts[pos]
    out["gap_ahead_s"] = gap
    return out


def clean_laps(raw: pd.DataFrame, threshold_max_lap: Optional[int] = None
               ) -> Tuple[pd.DataFrame, Dict[str, int], float]:
    """Apply the seven clean-lap steps. Returns (clean laps, counts, slow threshold).

    If threshold_max_lap is given, the fastest lap that sets the slow-lap threshold
    is searched only among laps with LapNumber <= threshold_max_lap.
    """
    d = raw.copy()
    d["lap_s"] = d["LapTime"]
    counts: Dict[str, int] = {}
    d = d[d["LapTime"].notna()]
    counts[STEP_NAMES[0]] = len(d)
    d = d[d["LapNumber"] >= 2]
    counts[STEP_NAMES[1]] = len(d)
    d = d[~d["is_pit_in_lap"].astype(bool) & ~d["is_pit_out_lap"].astype(bool)]
    counts[STEP_NAMES[2]] = len(d)
    d = d[d["TrackStatus"].astype(str) == "1"]
    counts[STEP_NAMES[3]] = len(d)
    d = d[d["IsAccurate"].astype(bool)]
    counts[STEP_NAMES[4]] = len(d)
    d = d[d["Compound"].isin(cfg.DRY_COMPOUNDS) & d["TyreLife"].notna()]
    counts[STEP_NAMES[5]] = len(d)
    ref = d if threshold_max_lap is None else d[d["LapNumber"] <= threshold_max_lap]
    if len(ref) == 0:
        counts[STEP_NAMES[6]] = 0
        return d.iloc[0:0], counts, float("nan")
    thr = cfg.SLOW_LAP_FACTOR * float(ref["lap_s"].min())
    d = d[d["lap_s"] <= thr]
    counts[STEP_NAMES[6]] = len(d)
    return d, counts, thr


def apply_compound_minimum(df: pd.DataFrame, min_laps: int = cfg.MIN_COMPOUND_LAPS
                           ) -> Tuple[pd.DataFrame, List[str]]:
    """Drop compounds with fewer than min_laps laps. Returns (laps, dropped)."""
    n = df["Compound"].value_counts()
    dropped = sorted(c for c in n.index if n[c] < min_laps)
    return df[~df["Compound"].isin(dropped)], dropped


def formula(model: str, response: str = "lap_s") -> str:
    """Model formula text for M0, M1 or M2."""
    return f"{response} ~ {RHS[model]}"


def fit_model(df: pd.DataFrame, model: str, response: str = "lap_s",
              cluster: bool = False):
    """Fit one OLS model. Standard errors clustered by driver if cluster is True."""
    m = smf.ols(formula(model, response), data=df)
    if cluster:
        codes = pd.factorize(df["Driver"])[0]
        return m.fit(cov_type="cluster", cov_kwds={"groups": codes})
    return m.fit()


def design_full_rank(df: pd.DataFrame, model: str) -> bool:
    """True if the design matrix has full column rank."""
    x = smf.ols(formula(model), data=df).exog
    return bool(np.linalg.matrix_rank(x) == x.shape[1])


def deg_rates(res) -> Dict[str, float]:
    """Linear TyreLife slope per compound from a fitted M1 or M2."""
    out = {}
    for name, val in res.params.items():
        if name.endswith(":TyreLife") and name.startswith("C(Compound)["):
            out[name[len("C(Compound)["):-len("]:TyreLife")]] = float(val)
    return out


def deg_ses(res) -> Dict[str, float]:
    """Standard error of the TyreLife slope per compound."""
    out = {}
    for name, val in res.bse.items():
        if name.endswith(":TyreLife") and name.startswith("C(Compound)["):
            out[name[len("C(Compound)["):-len("]:TyreLife")]] = float(val)
    return out


def mae(err: np.ndarray) -> float:
    """Mean absolute error."""
    return float(np.mean(np.abs(err)))


def rmse(err: np.ndarray) -> float:
    """Root mean squared error."""
    return float(np.sqrt(np.mean(np.square(err))))


def bias(pred: np.ndarray, actual: np.ndarray) -> float:
    """Mean of predicted minus actual."""
    return float(np.mean(np.asarray(pred) - np.asarray(actual)))


def full_race_fit(clean: pd.DataFrame) -> Optional[dict]:
    """Fit M1 on all clean laps after the compound minimum."""
    d, dropped = apply_compound_minimum(clean)
    if len(d) == 0:
        return None
    res = fit_model(d, "M1", cluster=True)
    rates, ses = deg_rates(res), deg_ses(res)
    return {
        "rates": rates, "ses": ses,
        "laps_by_compound": d["Compound"].value_counts().to_dict(),
        "lap_coef": float(res.params["LapNumber"]),
        "lap_coef_se": float(res.bse["LapNumber"]),
        "n_laps": int(len(d)), "n_drivers": int(d["Driver"].nunique()),
        "r2": float(res.rsquared), "resid_sd": float(np.sqrt(res.scale)),
        "dropped_compounds": dropped,
    }


def forecast_race(raw: pd.DataFrame, frac: float = cfg.TRAIN_FRACTION,
                  clean_air: bool = False) -> dict:
    """Fit M0, M1, M2 on laps up to the cutoff and predict the later laps."""
    if clean_air and "gap_ahead_s" not in raw.columns:
        raw = add_gap_ahead(raw)
    total = int(raw["LapNumber"].max())
    cutoff = int(math.floor(frac * total))
    clean, _, thr = clean_laps(raw, threshold_max_lap=cutoff)
    if clean_air:
        clean = clean[clean["gap_ahead_s"] > cfg.CLEAN_AIR_GAP_S]
    train = clean[clean["LapNumber"] <= cutoff]
    test = clean[clean["LapNumber"] > cutoff]
    train, dropped = apply_compound_minimum(train)
    n_test_before = len(test)
    test = test[test["Compound"].isin(set(train["Compound"]))]
    removed_compound = n_test_before - len(test)
    n1 = len(test)
    test = test[test["Driver"].isin(set(train["Driver"]))]
    removed_driver = n1 - len(test)
    out = {"total_laps": total, "cutoff": cutoff, "threshold": thr,
           "n_train": int(len(train)), "n_test": int(len(test)),
           "dropped_compounds": dropped,
           "removed_test_compound": int(removed_compound),
           "removed_test_driver": int(removed_driver),
           "removed_test_total": int(removed_compound + removed_driver),
           "eligible": False, "reason": "", "train": train, "test": test}
    if len(train) < cfg.MIN_TRAIN_LAPS:
        out["reason"] = f"train laps {len(train)} < {cfg.MIN_TRAIN_LAPS}"
        return out
    if len(test) < cfg.MIN_TEST_LAPS:
        out["reason"] = f"test laps {len(test)} < {cfg.MIN_TEST_LAPS}"
        return out
    for m in MODELS:
        if not design_full_rank(train, m):
            out["reason"] = f"{m} design not full rank"
            return out
    out["eligible"] = True
    t = test.copy()
    t["horizon"] = t["LapNumber"] - cutoff
    for m in MODELS:
        res = fit_model(train, m)
        pred = res.predict(t).to_numpy()
        t[f"pred_{m}"] = pred
        err = pred - t["lap_s"].to_numpy()
        out[f"MAE_{m}"] = mae(err)
        out[f"RMSE_{m}"] = rmse(err)
        out[f"bias_{m}"] = bias(pred, t["lap_s"].to_numpy())
        out[f"params_{m}"] = res.params.copy()
    out["test"] = t
    return out


def bootstrap_mean_ci(x: Sequence[float], reps: int = cfg.BOOTSTRAP_REPS,
                      seed: int = cfg.RANDOM_SEED) -> Tuple[float, float]:
    """2.5 and 97.5 percentiles of the bootstrap mean, resampling items."""
    a = np.asarray(x, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(reps, len(a)))
    means = a[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def naive_slope(stint: pd.DataFrame) -> float:
    """OLS slope of lap_s on TyreLife for one stint alone."""
    x = stint["TyreLife"].to_numpy(dtype=float)
    y = stint["lap_s"].to_numpy(dtype=float)
    xc = x - x.mean()
    return float((xc * (y - y.mean())).sum() / (xc ** 2).sum())


def naive_stint_slopes(clean: pd.DataFrame,
                       min_laps: int = cfg.MIN_STINT_LAPS_NAIVE) -> pd.DataFrame:
    """Naive slope for each stint with at least min_laps clean laps."""
    rows = []
    for (drv, stint), g in clean.groupby(["Driver", "Stint"]):
        if len(g) < min_laps or g["TyreLife"].nunique() < 2:
            continue
        rows.append({"Driver": drv, "Stint": stint,
                     "Compound": g["Compound"].mode().iloc[0],
                     "clean_laps": len(g),
                     "first_tyre_age": float(g["TyreLife"].min()),
                     "last_tyre_age": float(g["TyreLife"].max()),
                     "naive_slope": naive_slope(g)})
    return pd.DataFrame(rows)


def minisector_times(t: np.ndarray, rel: np.ndarray, n: int = cfg.N_MINISECTORS
                     ) -> np.ndarray:
    """Raw mini-sector times from elapsed time t at relative distance rel."""
    edges = np.interp(np.arange(n + 1) / n, rel, t)
    return np.diff(edges)


def rescale_to_lap(times: np.ndarray, lap_s: float) -> np.ndarray:
    """Scale mini-sector times so they sum to the official lap time."""
    return times * (lap_s / times.sum())
