"""Run the season study on the replication seasons and pool them."""
import os
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg
import expansion_config as xc
import f1deg as F
from replication import run_season

HERE = Path(__file__).resolve().parent


def main():
    out = HERE / "results/replication"
    out.mkdir(parents=True, exist_ok=True)
    allval, per = [], []
    notes = []
    for season in xc.REPLICATION_SEASONS:
        laps = pd.read_csv(HERE / f"data/laps_{season}.csv", dtype={"TrackStatus": str})
        races = pd.read_csv(HERE / f"data/races_{season}.csv")
        other = laps[~laps["Compound"].isin(cfg.DRY_COMPOUNDS + cfg.WET_COMPOUNDS) & laps["Compound"].notna()]
        notes.append({"season": season, "laps_other_compound_names": len(other),
                      "names": ";".join(sorted(other["Compound"].astype(str).unique())),
                      "laps_missing_compound": int(laps["Compound"].isna().sum())})
        res = run_season(laps, races)
        for name, df in res.items():
            df.to_csv(out / f"{season}_{name}.csv", index=False)
        v = res["validation"].copy()
        v.insert(0, "season", season)
        allval.append(v)
        s = res["summary"].set_index("metric")["value"]
        per.append({"season": season, **{k: s[k] for k in ["D1", "D1_lo", "D1_hi", "D2", "D2_lo", "D2_hi",
                                                           "validation_eligible_races", "wet_races", "failed_loads"]}})
    pd.DataFrame(notes).to_csv(out / "compound_name_notes.csv", index=False)
    val = pd.concat(allval, ignore_index=True)
    d1, d2 = val["MAE_M0_minus_M1"].to_numpy(), val["MAE_M1_minus_M2"].to_numpy()
    r1lo, r1hi = F.bootstrap_mean_ci(d1)
    r2lo, r2hi = F.bootstrap_mean_ci(d2)
    m = {"R1": d1.mean(), "R1_lo": r1lo, "R1_hi": r1hi, "R2": d2.mean(), "R2_lo": r2lo, "R2_hi": r2hi,
         "races_pooled": len(val), "races_M1_beat_M0": int((d1 > 0).sum()), "races_M2_beat_M1": int((d2 > 0).sum())}
    for mm in F.MODELS:
        m[f"pooled_test_MAE_{mm}"] = float(val[f"MAE_{mm}"].mean())
    for p in per:
        for k, v in p.items():
            if k != "season":
                m[f"{p['season']}_{k}"] = v
    v25 = pd.read_csv(HERE / "results/validation.csv")
    a1 = np.concatenate([d1, v25["MAE_M0_minus_M1"].to_numpy()])
    a2 = np.concatenate([d2, v25["MAE_M1_minus_M2"].to_numpy()])
    m["ALL4_D1"], m["ALL4_D2"] = a1.mean(), a2.mean()
    m["ALL4_D1_lo"], m["ALL4_D1_hi"] = F.bootstrap_mean_ci(a1)
    m["ALL4_D2_lo"], m["ALL4_D2_hi"] = F.bootstrap_mean_ci(a2)
    m["ALL4_races"] = len(a1)
    pd.DataFrame({"metric": list(m), "value": list(m.values()),
                  "label": ["original plus replication, shown for reference" if k.startswith("ALL4") else "" for k in m]}
                 ).to_csv(out / "pooled_summary.csv", index=False)
    if r1lo > 0:
        verdict = "The replication interval for R1 is above zero: the 2025 result held in 2022 to 2024."
    elif r1hi < 0:
        verdict = "The replication interval for R1 is below zero: the 2025 result reversed in 2022 to 2024."
    else:
        verdict = "The replication interval for R1 includes zero: the 2025 result was not confirmed in 2022 to 2024."
    (out / "verdict.txt").write_text(verdict + "\n")
    print(verdict)
    print({k: round(float(v), 4) for k, v in m.items() if k in ("R1", "R1_lo", "R1_hi", "races_pooled")})


if __name__ == "__main__":
    main()
