"""Corrected race pace for all seasons. Exploratory. Reads data/, writes results/pace/."""
from pathlib import Path

import numpy as np
import pandas as pd

import expansion_config as xc
import f1deg as F
import pace as P

HERE = Path(__file__).resolve().parent


def main():
    out = HERE / "results/pace"
    out.mkdir(parents=True, exist_ok=True)
    fits25 = pd.read_csv(HERE / "results/full_race_fits.csv")
    drv_rows, team_rows, comp_rows = [], [], []
    for season in xc.ALL_SEASONS:
        laps = pd.read_csv(HERE / f"data/laps_{season}.csv", dtype={"TrackStatus": str})
        races = pd.read_csv(HERE / f"data/races_{season}.csv")
        for _, r in races[races["load_status"] == "ok"].sort_values("Round").iterrows():
            rnd = int(r["Round"])
            raw = laps[laps["Round"] == rnd]
            if F.is_wet_race(raw):
                continue
            clean, _, _ = F.clean_laps(raw)
            if len(clean) == 0:
                continue
            res = P.race_pace(clean)
            if season == 2025:
                ref = fits25[fits25["Round"] == rnd].set_index("Compound")["deg_rate"]
                for c, v in res["rates"].items():
                    assert abs(v - ref[c]) < 1e-9, (rnd, c)
            base = {"season": season, "round": rnd, "event": r["EventName"]}
            for _, d in res["drivers"].iterrows():
                drv_rows.append({**base, **d.to_dict()})
            for _, t in P.team_pace(res["drivers"]).iterrows():
                team_rows.append({**base, **t.to_dict()})
            for k, v in P.compound_diffs(res["compound_effect"], res["rates"]).items():
                comp_rows.append({**base, "pair": k, "diff_at_age": v})
    dr = pd.DataFrame(drv_rows)
    tr = pd.DataFrame(team_rows)
    cr = pd.DataFrame(comp_rows)
    dr.to_csv(out / "driver_race.csv", index=False)
    tr.to_csv(out / "team_race.csv", index=False)
    cr.to_csv(out / "compound_race.csv", index=False)
    ts, tm, dv, cs = [], [], [], []
    for season in xc.ALL_SEASONS:
        t = P.team_ranking(tr[tr["season"] == season])
        t.insert(0, "season", season)
        ts.append(t)
        m = P.teammate_table(dr[dr["season"] == season])
        m.insert(0, "season", season)
        tm.append(m)
        d = P.development(tr[tr["season"] == season])
        d.insert(0, "season", season)
        dv.append(d)
        c = cr[cr["season"] == season].groupby("pair")["diff_at_age"].agg(["median", "size"]).reset_index()
        c.insert(0, "season", season)
        cs.append(c.rename(columns={"median": "median_diff", "size": "races"}))
    pd.concat(ts, ignore_index=True).to_csv(out / "team_season.csv", index=False)
    pd.concat(tm, ignore_index=True).to_csv(out / "teammates.csv", index=False)
    pd.concat(dv, ignore_index=True).to_csv(out / "development.csv", index=False)
    pd.concat(cs, ignore_index=True).to_csv(out / "compound_season.csv", index=False)
    print("driver-race rows:", len(dr), " team-race rows:", len(tr))


if __name__ == "__main__":
    main()
