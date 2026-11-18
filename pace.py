"""Tyre- and fuel-corrected race pace from the driver coefficients of model M1 (exploratory)."""
from typing import Dict, List

import numpy as np
import pandas as pd

import config as cfg
import expansion_config as xc
import f1deg as F


def race_pace(clean: pd.DataFrame, min_driver_laps: int = xc.MIN_DRIVER_LAPS) -> dict:
    """Fit M1 and return centred driver pace, compound effects and degradation rates."""
    d, dropped = F.apply_compound_minimum(clean)
    res = F.fit_model(d, "M1")
    params = res.params
    laps = d.groupby("Driver").size()
    eff = {}
    for drv in sorted(d["Driver"].unique()):
        eff[drv] = float(params.get(f"C(Driver)[T.{drv}]", 0.0))
    teams = d.groupby("Driver")["Team"].agg(lambda s: s.mode().iloc[0] if s.notna().any() else None)
    tab = pd.DataFrame({"driver": list(eff), "effect": list(eff.values()),
                        "laps": [int(laps[k]) for k in eff], "team": [teams[k] for k in eff]})
    tab["kept"] = tab["laps"] >= min_driver_laps
    mean_eff = tab.loc[tab["kept"], "effect"].mean()
    tab["pace"] = np.where(tab["kept"], tab["effect"] - mean_eff, np.nan)
    comp_eff = {c: float(params.get(f"C(Compound)[T.{c}]", 0.0)) for c in sorted(d["Compound"].unique())}
    return {"drivers": tab, "compound_effect": comp_eff, "rates": F.deg_rates(res), "dropped": dropped}


def team_pace(drivers: pd.DataFrame) -> pd.DataFrame:
    """Team pace in one race: mean pace of its kept drivers."""
    k = drivers[drivers["kept"]]
    g = k.groupby("team")["pace"].agg(["mean", "size"]).reset_index()
    return g.rename(columns={"mean": "team_pace", "size": "drivers"})


def team_ranking(team_race: pd.DataFrame, min_races: int = xc.MIN_RACES_TEAM) -> pd.DataFrame:
    """Mean team pace over races with indicative interval and rank (fastest first)."""
    rows = []
    for team, g in team_race.groupby("team"):
        if len(g) < min_races:
            continue
        lo, hi = F.bootstrap_mean_ci(g["team_pace"].to_numpy())
        rows.append({"team": team, "races": len(g), "mean_pace": float(g["team_pace"].mean()), "lo": lo, "hi": hi})
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values("mean_pace").reset_index(drop=True)
        df["rank"] = np.arange(1, len(df) + 1)
    return df


def teammate_table(driver_race: pd.DataFrame, min_races: int = xc.MIN_RACES_TEAMMATE) -> pd.DataFrame:
    """Mean pace difference (alphabetically first driver minus second) per same-team pair."""
    recs: Dict[tuple, List[float]] = {}
    for _, g in driver_race[driver_race["kept"]].groupby(["round"]):
        for team, gt in g.groupby("team"):
            ds = sorted(gt["driver"])
            pm = dict(zip(gt["driver"], gt["pace"]))
            for i in range(len(ds)):
                for j in range(i + 1, len(ds)):
                    recs.setdefault((team, ds[i], ds[j]), []).append(pm[ds[i]] - pm[ds[j]])
    rows = []
    for (team, a, b), v in recs.items():
        if len(v) < min_races:
            continue
        v = np.array(v)
        lo, hi = F.bootstrap_mean_ci(v)
        rows.append({"team": team, "driver_a": a, "driver_b": b, "races": len(v), "mean_diff": float(v.mean()),
                     "lo": lo, "hi": hi, "a_faster": int((v < 0).sum())})
    return pd.DataFrame(rows)


def slope(x: np.ndarray, y: np.ndarray) -> float:
    """Least-squares slope of y on x."""
    xc_ = x - x.mean()
    den = (xc_ ** 2).sum()
    return float((xc_ * (y - y.mean())).sum() / den) if den > 0 else float("nan")


def development(team_race: pd.DataFrame, min_races: int = xc.MIN_RACES_TEAM) -> pd.DataFrame:
    """Slope of team pace on round with a race-level bootstrap interval."""
    rows = []
    for team, g in team_race.groupby("team"):
        if len(g) < min_races:
            continue
        x, y = g["round"].to_numpy(float), g["team_pace"].to_numpy(float)
        rng = np.random.default_rng(cfg.RANDOM_SEED)
        idx = rng.integers(0, len(g), size=(cfg.BOOTSTRAP_REPS, len(g)))
        xs, ys = x[idx], y[idx]
        xcen = xs - xs.mean(axis=1, keepdims=True)
        den = (xcen ** 2).sum(axis=1)
        num = (xcen * (ys - ys.mean(axis=1, keepdims=True))).sum(axis=1)
        sl = num[den > 0] / den[den > 0]
        rows.append({"team": team, "races": len(g), "slope": slope(x, y),
                     "lo": float(np.percentile(sl, 2.5)), "hi": float(np.percentile(sl, 97.5))})
    return pd.DataFrame(rows)


def compound_diffs(comp_eff: Dict[str, float], rates: Dict[str, float],
                   age: int = xc.COMPOUND_COMPARE_AGE) -> Dict[str, float]:
    """Fitted lap time difference of compound x minus y at tyre age `age`."""
    out = {}
    cs = sorted(comp_eff)
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            x, y = cs[i], cs[j]
            out[f"{x}-{y}"] = (comp_eff[x] - comp_eff[y]) + age * (rates[x] - rates[y])
    return out
