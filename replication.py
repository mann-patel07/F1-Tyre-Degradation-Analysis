"""Season study as a function. Reproduces run_study.main() for any season's lap table."""
import numpy as np
import pandas as pd

import config as cfg
import f1deg as F


def _sens_row(raws, frac, clean_air):
    rows = []
    for raw in raws:
        o = F.forecast_race(raw, frac=frac, clean_air=clean_air)
        if o["eligible"]:
            rows.append((o["MAE_M0"] - o["MAE_M1"], o["MAE_M1"] - o["MAE_M2"]))
    a = np.array(rows) if rows else np.empty((0, 2))
    res = {"n_eligible": len(rows)}
    for i, name in enumerate(["D1", "D2"]):
        if len(a):
            lo, hi = F.bootstrap_mean_ci(a[:, i])
            res.update({name: float(a[:, i].mean()), f"{name}_lo": lo, f"{name}_hi": hi})
        else:
            res.update({name: np.nan, f"{name}_lo": np.nan, f"{name}_hi": np.nan})
    return res


def run_season(laps: pd.DataFrame, races: pd.DataFrame) -> dict:
    """Run the full study on one season. Returns a dict of data frames."""
    fc_rows, race_rows, fit_rows, val_rows, stint_rows = [], [], [], [], []
    horizon_frames, raws = [], []
    n_clean_total = 0
    for _, r in races.iterrows():
        rnd = int(r["Round"])
        base = {"Round": rnd, "EventName": r["EventName"]}
        if r["load_status"] != "ok":
            race_rows.append({**base, "total_laps": np.nan, "status": "load_failed",
                              "eligible": False, "reason": "load_failed"})
            continue
        raw = laps[laps["Round"] == rnd].copy()
        total = int(raw["LapNumber"].max())
        if F.is_wet_race(raw):
            race_rows.append({**base, "total_laps": total, "status": "wet", "eligible": False,
                              "reason": "wet race", "mean_track_temp": r["mean_track_temp"]})
            continue
        raw = F.add_gap_ahead(raw)
        raws.append(raw)
        clean, counts, _ = F.clean_laps(raw)
        fc_rows.append({**base, "raw_laps": len(raw), **counts})
        n_clean_total += len(clean)
        fit = F.full_race_fit(clean)
        if fit is not None:
            for comp, rate in fit["rates"].items():
                fit_rows.append({**base, "Compound": comp, "deg_rate": rate,
                                 "deg_se": fit["ses"][comp], "laps": fit["laps_by_compound"][comp],
                                 "lap_coef": fit["lap_coef"], "lap_coef_se": fit["lap_coef_se"],
                                 "r2": fit["r2"], "resid_sd": fit["resid_sd"],
                                 "n_laps": fit["n_laps"], "n_drivers": fit["n_drivers"]})
        st = F.naive_stint_slopes(clean)
        if len(st):
            st.insert(0, "EventName", r["EventName"])
            st.insert(0, "Round", rnd)
            stint_rows.append(st)
        o = F.forecast_race(raw)
        race_rows.append({**base, "total_laps": total, "status": "used",
                          "eligible": o["eligible"], "reason": o["reason"],
                          "cutoff_lap": o["cutoff"], "train_laps": o["n_train"],
                          "test_laps": o["n_test"], "compounds_dropped": ";".join(o["dropped_compounds"]),
                          "test_laps_removed": o["removed_test_total"],
                          "mean_track_temp": r["mean_track_temp"]})
        if o["eligible"]:
            t = o["test"]
            assert (t["LapNumber"] > o["cutoff"]).all()
            row = dict(base)
            for m in F.MODELS:
                row.update({f"MAE_{m}": o[f"MAE_{m}"], f"RMSE_{m}": o[f"RMSE_{m}"], f"bias_{m}": o[f"bias_{m}"]})
            row["MAE_M0_minus_M1"] = o["MAE_M0"] - o["MAE_M1"]
            row["MAE_M1_minus_M2"] = o["MAE_M1"] - o["MAE_M2"]
            val_rows.append(row)
            horizon_frames.append(t[["horizon", "lap_s"] + [f"pred_{m}" for m in F.MODELS]])
    races_out = pd.DataFrame(race_rows)
    fits = pd.DataFrame(fit_rows)
    val = pd.DataFrame(val_rows)
    stints = pd.concat(stint_rows, ignore_index=True) if stint_rows else pd.DataFrame()
    n_elig = len(val)
    assert n_elig == int(races_out["eligible"].sum())
    hz_rows = []
    s = {"races_in_season": len(races_out), "wet_races": int((races_out["status"] == "wet").sum()),
         "failed_loads": int((races_out["status"] == "load_failed").sum()),
         "validation_eligible_races": n_elig, "total_clean_laps_used": n_clean_total}
    if n_elig:
        hz = pd.concat(horizon_frames, ignore_index=True)
        for lo, hi in cfg.HORIZON_BUCKETS:
            b = hz[(hz["horizon"] >= lo) & (hz["horizon"] <= hi)]
            row = {"bucket": f"{lo}-{hi}" if hi < 999 else f"{lo}+", "laps": len(b)}
            for m in F.MODELS:
                row[f"MAE_{m}"] = F.mae(b[f"pred_{m}"] - b["lap_s"]) if len(b) else np.nan
            hz_rows.append(row)
        d1 = val["MAE_M0_minus_M1"].to_numpy()
        d2 = val["MAE_M1_minus_M2"].to_numpy()
        d1lo, d1hi = F.bootstrap_mean_ci(d1)
        d2lo, d2hi = F.bootstrap_mean_ci(d2)
        s.update({"D1": d1.mean(), "D1_lo": d1lo, "D1_hi": d1hi, "D2": d2.mean(), "D2_lo": d2lo, "D2_hi": d2hi,
                  "races_M1_beat_M0": int((d1 > 0).sum()), "races_M2_beat_M1": int((d2 > 0).sum())})
    else:
        s.update({k: np.nan for k in ["D1", "D1_lo", "D1_hi", "D2", "D2_lo", "D2_hi"]})
        s.update({"races_M1_beat_M0": 0, "races_M2_beat_M1": 0})
    s["lap_coef_median"] = float(fits.drop_duplicates("Round")["lap_coef"].median()) if len(fits) else np.nan
    s["naive_share_negative"] = float((stints["naive_slope"] < 0).mean()) if len(stints) else np.nan
    s["naive_stints"] = len(stints)
    for m in F.MODELS:
        if n_elig:
            s[f"pooled_test_MAE_{m}"] = F.mae(hz[f"pred_{m}"] - hz["lap_s"])
            s[f"pooled_test_RMSE_{m}"] = F.rmse(hz[f"pred_{m}"] - hz["lap_s"])
            s[f"pooled_test_bias_{m}"] = F.bias(hz[f"pred_{m}"], hz["lap_s"])
        else:
            for k in ("MAE", "RMSE", "bias"):
                s[f"pooled_test_{k}_{m}"] = np.nan
    for comp in cfg.DRY_COMPOUNDS:
        sub = fits[fits["Compound"] == comp] if len(fits) else fits
        s[f"median_deg_rate_{comp}"] = float(sub["deg_rate"].median()) if len(sub) else np.nan
        s[f"deg_rate_races_{comp}"] = len(sub)
    summary = pd.DataFrame({"metric": list(s), "value": list(s.values())})
    sens_t = pd.DataFrame([{"train_fraction": f, **_sens_row(raws, f, False)} for f in cfg.TRAIN_FRACTION_GRID])
    sens_a = pd.DataFrame([{"train_fraction": cfg.TRAIN_FRACTION, **_sens_row(raws, cfg.TRAIN_FRACTION, True)}])
    return {"races": races_out, "filter_counts": pd.DataFrame(fc_rows), "full_race_fits": fits,
            "validation": val, "stints": stints, "horizon": pd.DataFrame(hz_rows), "summary": summary,
            "sensitivity_train_fraction": sens_t, "sensitivity_clean_air": sens_a}
