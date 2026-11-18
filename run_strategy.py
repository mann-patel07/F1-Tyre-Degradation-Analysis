"""Pit strategy analysis over all seasons. Exploratory. Reads data/, writes results/strategy/."""
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg
import expansion_config as xc
import f1deg as F
import strategy as S

HERE = Path(__file__).resolve().parent
CIRCS = S.PRIMARY_ORDER


def boot_median(per_race, reps=cfg.BOOTSTRAP_REPS, seed=cfg.RANDOM_SEED):
    """Race-level bootstrap of a pooled median. per_race is a list of arrays (one per race)."""
    rng = np.random.default_rng(seed)
    n = len(per_race)
    idx = rng.integers(0, n, size=(reps, n))
    return np.array([np.median(np.concatenate([per_race[j] for j in row])) for row in idx])


def boot_diff(a_races, b_races, reps=cfg.BOOTSTRAP_REPS, seed=cfg.RANDOM_SEED):
    """Race-level bootstrap of a difference of pooled medians (green minus other)."""
    rng = np.random.default_rng(seed)
    rids = sorted(set(a_races) | set(b_races))
    out = []
    for _ in range(reps):
        pick = rng.integers(0, len(rids), size=len(rids))
        a = [a_races[rids[j]] for j in pick if rids[j] in a_races]
        b = [b_races[rids[j]] for j in pick if rids[j] in b_races]
        if not a or not b:
            continue
        out.append(np.median(np.concatenate(a)) - np.median(np.concatenate(b)))
    return np.array(out)


def main():
    out = HERE / "results/strategy"
    out.mkdir(parents=True, exist_ok=True)
    ch_rows, pass_rows, ref_rows, drv_rows, tl_rows, race_rows, log_rows = [], [], [], [], [], [], []
    for season in xc.ALL_SEASONS:
        laps = pd.read_csv(HERE / f"data/laps_{season}.csv", dtype={"TrackStatus": str})
        races = pd.read_csv(HERE / f"data/races_{season}.csv")
        print(season, "distinct TrackStatus:", sorted(laps["TrackStatus"].dropna().unique()))
        log_rows.append({"season": season, "distinct_track_status": ";".join(sorted(laps["TrackStatus"].dropna().unique()))})
        for _, r in races[races["load_status"] == "ok"].sort_values("Round").iterrows():
            rnd = int(r["Round"])
            raw = laps[laps["Round"] == rnd]
            a = S.analyse_race(raw)
            ref = a["reference"]
            base = {"season": season, "round": rnd, "event": r["EventName"]}
            for c in a["changes"]:
                ch_rows.append({**base, **c, "incomplete_race": a["incomplete"], "sentence": S.stop_sentence(c)})
            for p in a["passes"]:
                pass_rows.append({**base, **p})
            ref_rows.append({**base, "incomplete": a["incomplete"], "reference_stops": ref["n_stops"],
                             "reference_laps": ";".join("" if v is None else f"{v:g}" for v in ref["laps"].values()),
                             "qualifying_stops": ";".join(str(v) for v in ref["qualifying"].values()),
                             "reference_sequences": " | ".join(ref["sequences"]),
                             "artifacts": a["artifacts"],
                             "pit_passes": sum(1 for p in a["passes"] if p["kind"] == "PIT_PASS"),
                             "same_tyre_continuations": sum(1 for p in a["passes"] if p["kind"] == "SAME_TYRE_CONTINUATION")})
            for L in a["labels"]:
                drv_rows.append({**base, **L})
            tl = S.status_timeline(raw)
            tl.insert(0, "round", rnd)
            tl.insert(0, "season", season)
            tl_rows.append(tl)
            ch = pd.DataFrame(a["changes"])
            lab = pd.DataFrame(a["labels"])
            comp = lab[lab["completed"]]
            row = {**base, "incomplete": a["incomplete"], "tyre_changes": len(ch)}
            for c in CIRCS:
                row[f"share_{c}"] = float((ch["primary"] == c).mean()) if len(ch) else np.nan
            if len(ch):
                assert abs(sum(row[f"share_{c}"] for c in CIRCS) - 1) < 1e-9
            row["share_differs"] = float((comp["label"] == "DIFFERS").mean()) if len(comp) else np.nan
            dif = [s.split(":")[1] for x in comp[comp["label"] == "DIFFERS"]["differing_stops"] for s in x.split(";") if s]
            row["common_primary_among_differing"] = pd.Series(dif).mode().iloc[0] if dif else ""
            if len(ch):
                pit = ch[ch["pit_stop"]]
                for name, m in (("green", pit["in_green"] & ~pit["tag_SAFETY_CAR"] & ~pit["tag_VIRTUAL_SAFETY_CAR"]),
                                ("sc", pit["tag_SAFETY_CAR"]), ("vsc", pit["tag_VIRTUAL_SAFETY_CAR"])):
                    v = pit[m]["cost"].dropna()
                    row[f"cost_{name}_median"] = float(v.median()) if len(v) else np.nan
                    row[f"cost_{name}_n"] = len(v)
            race_rows.append(row)
            if len(ch):
                prim = ch.groupby("primary").size()
                assert prim.sum() == len(ch)
    changes = pd.DataFrame(ch_rows)
    # every stint boundary is an artifact or exactly one change: ensured by find_changes; one primary each
    assert changes["primary"].notna().all()
    changes.to_csv(out / "changes.csv", index=False)
    pd.DataFrame(pass_rows).to_csv(out / "pit_passes.csv", index=False)
    pd.DataFrame(ref_rows).to_csv(out / "reference.csv", index=False)
    drivers = pd.DataFrame(drv_rows)
    drivers.to_csv(out / "drivers.csv", index=False)
    pd.concat(tl_rows).to_csv(out / "status_timeline.csv", index=False)
    rs = pd.DataFrame(race_rows)
    rs.to_csv(out / "race_summary.csv", index=False)
    pd.DataFrame(log_rows).to_csv(out / "track_status_values.csv", index=False)

    ok = changes[~changes["incomplete_race"]].copy()
    ok["race_key"] = ok["season"].astype(str) + "_" + ok["round"].astype(str)
    ok_drv = drivers[(~drivers.set_index(["season", "round"]).index.isin(
        changes[changes["incomplete_race"]].set_index(["season", "round"]).index))]
    srows = []

    def add(season, group, metric, value, lo=None, hi=None, n=None, n_races=None, note=""):
        srows.append({"season": season, "group": group, "metric": metric, "value": value, "lo": lo, "hi": hi,
                      "n": n, "n_races": n_races, "note": note})

    for season in [str(s) for s in xc.ALL_SEASONS] + ["ALL"]:
        sub = ok if season == "ALL" else ok[ok["season"] == int(season)]
        dsub = ok_drv if season == "ALL" else ok_drv[ok_drv["season"] == int(season)]
        add(season, "all", "tyre_changes", len(sub), n=len(sub), n_races=sub["race_key"].nunique())
        for c in CIRCS:
            add(season, c, "share_of_changes", float((sub["primary"] == c).mean()) if len(sub) else np.nan,
                n=int((sub["primary"] == c).sum()), n_races=sub[sub["primary"] == c]["race_key"].nunique())
        pit = sub[sub["pit_stop"] & sub["cost"].notna()]
        groups = {"green": pit[pit["in_green"] & ~pit["tag_SAFETY_CAR"] & ~pit["tag_VIRTUAL_SAFETY_CAR"]],
                  "SAFETY_CAR": pit[pit["tag_SAFETY_CAR"]], "VIRTUAL_SAFETY_CAR": pit[pit["tag_VIRTUAL_SAFETY_CAR"]]}
        per = {}
        for g, df in groups.items():
            per[g] = {k: v["cost"].to_numpy() for k, v in df.groupby("race_key")}
            nr = len(per[g])
            med = float(df["cost"].median()) if len(df) else np.nan
            if nr >= 3:
                b = boot_median(list(per[g].values()))
                add(season, g, "median_stop_cost_s", med, float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5)), len(df), nr)
            else:
                add(season, g, "median_stop_cost_s", med, None, None, len(df), nr, "fewer than 3 races, no interval")
        for g in ("SAFETY_CAR", "VIRTUAL_SAFETY_CAR"):
            if len(per["green"]) >= 3 and len(per[g]) >= 3:
                d = boot_diff(per["green"], per[g])
                val = float(groups["green"]["cost"].median() - groups[g]["cost"].median())
                add(season, g, "green_minus_median_stop_cost_s", val, float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)),
                    len(groups["green"]) + len(groups[g]), len(set(per["green"]) | set(per[g])))
            else:
                add(season, g, "green_minus_median_stop_cost_s", np.nan, note="a group has stops in fewer than 3 races")
        for c in CIRCS:
            v = sub[sub["primary"] == c]["pos_change"].dropna()
            add(season, c, "median_position_change", float(v.median()) if len(v) else np.nan, n=len(v),
                n_races=sub[sub["primary"] == c]["race_key"].nunique())
        oc = sub[sub["tag_UNDERCUT_ATTEMPT"]]["undercut_outcome"].value_counts()
        for k in ("SUCCEEDED", "FAILED", "NOT_RESOLVED"):
            add(season, k, "undercut_count", int(oc.get(k, 0)), n=int(oc.get(k, 0)))
        res = int(oc.get("SUCCEEDED", 0) + oc.get("FAILED", 0))
        add(season, "undercut", "success_share_of_resolved", float(oc.get("SUCCEEDED", 0) / res) if res else np.nan, n=res)
        comp = dsub[dsub["completed"]]
        add(season, "drivers", "share_differs", float((comp["label"] == "DIFFERS").mean()) if len(comp) else np.nan,
            n=int((comp["label"] == "DIFFERS").sum()), n_races=comp.groupby(["season", "round"]).ngroups)
        add(season, "drivers", "completing_drivers", len(comp), n=len(comp))
    pd.DataFrame(srows).to_csv(out / "season_summary.csv", index=False)
    print("tyre changes:", len(changes), " races:", len(rs), " incomplete:", int(rs["incomplete"].sum()))


if __name__ == "__main__":
    main()
