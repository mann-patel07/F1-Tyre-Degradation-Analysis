"""Exploratory rank correlations across modules. Reads results/, writes results/links.csv."""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import expansion_config as xc

HERE = Path(__file__).resolve().parent


def _fits(season):
    p = HERE / ("results/full_race_fits.csv" if season == 2025 else f"results/replication/{season}_full_race_fits.csv")
    return pd.read_csv(p)


def _val(season):
    p = HERE / ("results/validation.csv" if season == 2025 else f"results/replication/{season}_validation.csv")
    return pd.read_csv(p)


def main():
    deg = []
    for s in xc.ALL_SEASONS:
        f = _fits(s)
        g = f.groupby("Round").apply(lambda x: np.average(x["deg_rate"], weights=x["laps"]), include_groups=False)
        deg.append(pd.DataFrame({"season": s, "round": g.index, "deg_index": g.values}))
    d = pd.concat(deg, ignore_index=True)
    ref = pd.read_csv(HERE / "results/strategy/reference.csv")
    ref = ref[~ref["incomplete"]][["season", "round", "reference_stops"]]
    rs = pd.read_csv(HERE / "results/strategy/race_summary.csv")
    rs = rs[~rs["incomplete"]][["season", "round", "share_differs"]]
    gain = pd.concat([_val(s).assign(season=s).rename(columns={"Round": "round"})[["season", "round", "MAE_M0_minus_M1"]]
                      for s in xc.ALL_SEASONS], ignore_index=True)
    tel = pd.read_csv(HERE / "results/telemetry_season/race_compound.csv")
    tel = tel[tel["is_primary"]][["round", "G"]].assign(season=xc.TELEMETRY_SEASON)
    links = [("deg_index vs reference number of stops", d.merge(ref, on=["season", "round"]), "reference_stops"),
             ("deg_index vs share of completing drivers labeled DIFFERS", d.merge(rs, on=["season", "round"]), "share_differs"),
             ("deg_index vs forecast gain (MAE_M0 minus MAE_M1)", d.merge(gain, on=["season", "round"]), "MAE_M0_minus_M1"),
             ("deg_index vs density difference G (2025 only)", d.merge(tel, on=["season", "round"]), "G")]
    rows = []
    for name, df, col in links:
        df = df.dropna(subset=["deg_index", col])
        for season in [str(s) for s in xc.ALL_SEASONS] + ["ALL"]:
            sub = df if season == "ALL" else df[df["season"] == int(season)]
            if len(sub) >= 3 and sub[col].nunique() > 1:
                r = spearmanr(sub["deg_index"], sub[col])
                rows.append({"link": name, "season": season, "races": len(sub), "rho": float(r.statistic), "p_value": float(r.pvalue)})
            else:
                rows.append({"link": name, "season": season, "races": len(sub), "rho": np.nan, "p_value": np.nan})
    pd.DataFrame(rows).to_csv(HERE / "results/links.csv", index=False)
    print("links rows:", len(rows))


if __name__ == "__main__":
    main()
