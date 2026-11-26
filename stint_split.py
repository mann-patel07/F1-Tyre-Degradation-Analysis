"""Stint split of D1. Added after the first version (see UPGRADE_PLAN.md).

Each test lap is "continuing" if its driver and stint number also appear among that race's training laps
(the stint began before the cutoff), and "new stint" otherwise. For each group, D1 = MAE(M0) - MAE(M1) and
D2 = MAE(M1) - MAE(M2) are computed per race, then averaged over races.
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd

import expansion_config as xc
import f1deg as F

MIN_GROUP_LAPS = 20
HERE = Path(__file__).resolve().parent
GROUPS = ["continuing", "new"]


def continuing_mask(test, train):
    """True for each test lap whose (Driver, Stint) is among the training laps."""
    seen = set(zip(train["Driver"], train["Stint"]))
    return np.array([(d, s) in seen for d, s in zip(test["Driver"], test["Stint"])], dtype=bool)


def group_maes(test, mask):
    """MAE of M0, M1 and M2 on the laps selected by mask, and the lap count. No minimum applied."""
    sub = test[mask]
    out = {"n": int(len(sub))}
    for m in F.MODELS:
        out[f"MAE_{m}"] = float(np.mean(np.abs(sub[f"pred_{m}"] - sub["lap_s"]))) if len(sub) else np.nan
    return out


def group_row(test, mask, min_laps=MIN_GROUP_LAPS):
    """MAE, D1 and D2 for one group. D1 and D2 are NaN if the group has fewer than min_laps laps."""
    g = group_maes(test, mask)
    if g["n"] < min_laps:
        return {**{k: np.nan for k in ("MAE_M0", "MAE_M1", "MAE_M2", "D1", "D2")}, "n": g["n"]}
    g["D1"] = g["MAE_M0"] - g["MAE_M1"]
    g["D2"] = g["MAE_M1"] - g["MAE_M2"]
    return g


def eligible_races(season):
    """Run the first version's race skipping and forecast. Returns a list of (row dict, forecast output)."""
    laps = pd.read_csv(HERE / f"data/laps_{season}.csv", dtype={"TrackStatus": str})
    races = pd.read_csv(HERE / f"data/races_{season}.csv")
    out = []
    for _, r in races.iterrows():
        if r["load_status"] != "ok":
            continue
        raw = laps[laps["Round"] == int(r["Round"])].copy()
        if F.is_wet_race(raw):
            continue
        raw = F.add_gap_ahead(raw)
        o = F.forecast_race(raw)
        if not o["eligible"]:
            continue
        out.append(({"season": season, "Round": int(r["Round"]), "EventName": r["EventName"]}, o))
    return out


def by_race(season):
    first = pd.read_csv(HERE / ("results/validation.csv" if season == 2025
                                else f"results/replication/{season}_validation.csv"))
    rows = []
    found = eligible_races(season)
    if sorted(b["Round"] for b, _ in found) != sorted(first["Round"].astype(int)):
        raise SystemExit(f"eligible rounds for {season} differ from the first version")
    for base, o in found:
        t, tr = o["test"], o["train"]
        mask = continuing_mask(t, tr)
        c, n = group_row(t, mask), group_row(t, ~mask)
        row = {**base, "n_continuing": c["n"], "n_new": n["n"]}
        for k in ("MAE_M0", "MAE_M1", "MAE_M2", "D1", "D2"):
            row[f"{k}_continuing"] = c[k]
        for k in ("MAE_M0", "MAE_M1", "MAE_M2", "D1", "D2"):
            row[f"{k}_new"] = n[k]
        rows.append(row)
    return pd.DataFrame(rows)


COLUMNS = ["season", "Round", "EventName", "n_continuing", "n_new",
           "MAE_M0_continuing", "MAE_M1_continuing", "MAE_M2_continuing", "D1_continuing", "D2_continuing",
           "MAE_M0_new", "MAE_M1_new", "MAE_M2_new", "D1_new", "D2_new"]


def summarize(df, scope):
    """Rows (scope, group, metric, value) for one set of per-race rows."""
    rows = []
    total = df["n_continuing"].sum() + df["n_new"].sum()
    for g in GROUPS:
        d1 = df[f"D1_{g}"].dropna().to_numpy()
        d2 = df[f"D2_{g}"].dropna().to_numpy()
        n_laps = df[f"n_{g}"].sum()
        vals = {"races": len(d1), "D1_above_zero": int((d1 > 0).sum()), "share_of_test_laps": n_laps / total}
        for name, a in (("D1", d1), ("D2", d2)):
            if len(a):
                lo, hi = F.bootstrap_mean_ci(a)
                vals.update({name: float(a.mean()), f"{name}_lo": lo, f"{name}_hi": hi})
            else:
                vals.update({name: np.nan, f"{name}_lo": np.nan, f"{name}_hi": np.nan})
        for metric in ("races", "D1", "D1_lo", "D1_hi", "D1_above_zero", "D2", "D2_lo", "D2_hi", "share_of_test_laps"):
            rows.append({"scope": scope, "group": g, "metric": metric, "value": vals[metric]})
    return rows


def main():
    t0 = time_start = time.time()
    out = HERE / "results/stint_split"
    out.mkdir(parents=True, exist_ok=True)
    frames, summary = {}, []
    for season in [2025] + xc.REPLICATION_SEASONS:
        df = by_race(season)
        df[COLUMNS].to_csv(out / f"{season}_by_race.csv", index=False)
        frames[season] = df
        summary += summarize(df, str(season))
        print(season, "races", len(df), flush=True)
    pooled = pd.concat([frames[s] for s in xc.REPLICATION_SEASONS], ignore_index=True)
    summary += summarize(pooled, "2022-2024 pooled")
    pd.DataFrame(summary).to_csv(out / "summary.csv", index=False)
    s = pd.DataFrame(summary)
    print(s[s.metric.isin(["races", "D1", "D1_lo", "D1_hi", "share_of_test_laps"])].to_string(index=False))
    print("run time %.1f s" % (time.time() - time_start))


if __name__ == "__main__":
    main()
