"""Telemetry case study: mini-sector degradation for one race."""
import os
import sys
import time
from pathlib import Path

import fastf1
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection

import config as cfg
import f1deg as F

N = cfg.N_MINISECTORS
COMP_COLORS = {"SOFT": "#c0392b", "MEDIUM": "#d4a017", "HARD": "#555555"}


def log(msg):
    with open("RUN_LOG.md", "a") as f:
        f.write(f"- 2026-11-16: {msg}\n")


def load_session(rnd):
    last = None
    for attempt in range(cfg.LOAD_RETRIES):
        try:
            s = fastf1.get_session(cfg.SEASON, rnd, cfg.SESSION_TYPE)
            s.load(laps=True, telemetry=True, weather=False, messages=False)
            if len(s.laps) > 0:
                return s
            last = "empty"
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        if attempt < cfg.LOAD_RETRIES - 1:
            time.sleep(cfg.RETRY_WAIT_S)
    log(f"Telemetry load failed: {last}")
    return None


def lap_t_rel(lap):
    car = lap.get_car_data().add_distance()
    t = (car["SessionTime"] - car["SessionTime"].iloc[0]).dt.total_seconds().to_numpy()
    rel = (car["Distance"] / car["Distance"].iloc[-1]).to_numpy()
    return car, t, rel


def main():
    Path("results").mkdir(exist_ok=True)
    Path("Images").mkdir(exist_ok=True)
    races = pd.read_csv("data/races_2025.csv")
    laps = pd.read_csv("data/laps_2025.csv", dtype={"TrackStatus": str})
    hit = races[races["EventName"] == cfg.CASE_STUDY_EVENT]
    if len(hit) != 1 or hit.iloc[0]["load_status"] != "ok":
        log("Stage 5 skipped: case study race missing or failed to load.")
        print("Stage 5 skipped")
        return
    rnd = int(hit.iloc[0]["Round"])
    raw = laps[laps["Round"] == rnd]
    if F.is_wet_race(raw):
        log("Stage 5 skipped: case study race is wet.")
        print("Stage 5 skipped (wet)")
        return
    os.makedirs(cfg.CACHE_DIR, exist_ok=True)
    fastf1.Cache.enable_cache(cfg.CACHE_DIR)
    session = load_session(rnd)
    if session is None:
        print("Stage 5 skipped (telemetry load failed)")
        return
    clean, counts, _ = F.clean_laps(raw)
    fc = pd.read_csv("results/filter_counts.csv")
    assert counts["s7_not_slow"] == int(fc[fc["Round"] == rnd]["s7_not_slow"].iloc[0])
    clean, dropped_comp = F.apply_compound_minimum(clean)
    sl = session.laps
    rows, mism = [], []
    ndrop = 0
    for _, r in clean.iterrows():
        m = sl[(sl["Driver"] == r["Driver"]) & (sl["LapNumber"] == r["LapNumber"])]
        if len(m) != 1:
            ndrop += 1
            continue
        try:
            _, t, rel = lap_t_rel(m.iloc[0])
            ms = F.minisector_times(t, rel)
        except Exception:  # noqa: BLE001
            ndrop += 1
            continue
        mismatch = abs(ms.sum() - r["lap_s"])
        if not np.isfinite(mismatch) or mismatch > cfg.MAX_LAPTIME_MISMATCH_S:
            ndrop += 1
            mism.append(mismatch)
            continue
        mism.append(mismatch)
        ms = F.rescale_to_lap(ms, r["lap_s"])
        rows.append({"Driver": r["Driver"], "LapNumber": int(r["LapNumber"]),
                     "Stint": int(r["Stint"]), "Compound": r["Compound"],
                     "TyreLife": r["TyreLife"], "lap_s": r["lap_s"],
                     **{f"ms_{k}": ms[k] for k in range(N)}})
    ms_df = pd.DataFrame(rows)
    ms_df.to_csv("data/bahrain_minisectors.csv", index=False)
    mm = np.array(mism, dtype=float)
    quality = {"clean_laps": len(clean), "kept": len(ms_df), "dropped": ndrop,
               "mismatch_mean": float(np.nanmean(mm)), "mismatch_median": float(np.nanmedian(mm)),
               "mismatch_max": float(np.nanmax(mm))}
    pd.DataFrame([quality]).to_csv("results/telemetry_quality.csv", index=False)
    print(quality)

    d, dropped2 = F.apply_compound_minimum(ms_df)
    if dropped2:
        log(f"Telemetry: compounds dropped after mismatch filter: {dropped2}")
    ms_df = d
    res_lap = F.fit_model(ms_df, "M1")
    lap_rates = F.deg_rates(res_lap)
    comps = sorted(lap_rates)
    fit_rows = []
    sum_rates = {c: 0.0 for c in comps}
    sum_lapcoef = 0.0
    for k in range(N):
        res = F.fit_model(ms_df, "M1", response=f"ms_{k}")
        rates = F.deg_rates(res)
        row = {"minisector": k, "lap_coef": float(res.params["LapNumber"]),
               "mean_time_s": float(ms_df[f"ms_{k}"].mean())}
        for c in comps:
            row[f"deg_rate_{c}"] = rates[c]
            sum_rates[c] += rates[c]
        sum_lapcoef += row["lap_coef"]
        fit_rows.append(row)
    fits = pd.DataFrame(fit_rows)
    fits.to_csv("results/minisector_fits.csv", index=False)
    for c in comps:
        assert abs(sum_rates[c] - lap_rates[c]) < 1e-6, (c, sum_rates[c], lap_rates[c])
    assert abs(sum_lapcoef - res_lap.params["LapNumber"]) < 1e-6
    lin = {"compound": comps + ["LapNumber"],
           "sum_of_minisectors": [sum_rates[c] for c in comps] + [sum_lapcoef],
           "lap_time_fit": [lap_rates[c] for c in comps] + [float(res_lap.params["LapNumber"])]}
    pd.DataFrame(lin).to_csv("results/linearity_check.csv", index=False)

    ref_row = ms_df.loc[ms_df["lap_s"].idxmin()]
    m = sl[(sl["Driver"] == ref_row["Driver"]) & (sl["LapNumber"] == ref_row["LapNumber"])].iloc[0]
    ref = m.get_telemetry()
    ref_rel = (ref["Distance"] / ref["Distance"].iloc[-1]).to_numpy()
    idx = np.minimum((ref_rel * N).astype(int), N - 1)
    classes = []
    for k in range(N):
        sel = idx == k
        if not sel.any():
            log(f"Mini-sector {k} has no reference samples; labelled CORNER.")
            classes.append("CORNER")
        else:
            classes.append("STRAIGHT" if ref["Throttle"].to_numpy()[sel].min()
                           >= cfg.STRAIGHT_THROTTLE_MIN else "CORNER")
    pd.DataFrame({"rel": ref_rel, "X": ref["X"].to_numpy(), "Y": ref["Y"].to_numpy(),
                  "Speed": ref["Speed"].to_numpy(), "Throttle": ref["Throttle"].to_numpy(),
                  "minisector": idx, "class": [classes[i] for i in idx]}
                 ).to_csv("data/bahrain_reference_lap.csv", index=False)
    cls = np.array(classes)
    _, rt, rrel = lap_t_rel(m)
    rms = F.rescale_to_lap(F.minisector_times(rt, rrel), ref_row["lap_s"])
    out_rows = []
    for c in comps:
        rates = fits[f"deg_rate_{c}"].to_numpy()
        tot = rates.sum()
        cs, ss = rates[cls == "CORNER"].sum(), rates[cls == "STRAIGHT"].sum()
        out_rows.append({"compound": c, "total_rate": tot, "corner_rate": cs,
                         "straight_rate": ss, "corner_share": cs / tot,
                         "straight_share": ss / tot,
                         "ref_time_share_corner": rms[cls == "CORNER"].sum() / rms.sum(),
                         "ref_time_share_straight": rms[cls == "STRAIGHT"].sum() / rms.sum(),
                         "n_corner_minisectors": int((cls == "CORNER").sum()),
                         "n_straight_minisectors": int((cls == "STRAIGHT").sum())})
    pd.DataFrame(out_rows).to_csv("results/corner_vs_straight.csv", index=False)

    main_comp = ms_df["Compound"].value_counts().idxmax()
    rate = fits[f"deg_rate_{main_comp}"].to_numpy()
    x, y = ref["X"].to_numpy(), ref["Y"].to_numpy()
    pts = np.column_stack([x, y]).reshape(-1, 1, 2)
    segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
    fig, ax = plt.subplots(figsize=(7, 6))
    lc = LineCollection(segs, cmap="viridis", linewidth=4)
    lc.set_array(rate[idx[:-1]])
    ax.add_collection(lc)
    ax.autoscale()
    ax.set_aspect("equal")
    ax.axis("off")
    fig.colorbar(lc, ax=ax, label="Fitted degradation rate (s per lap of tyre age)")
    ax.set_title(f"Fitted degradation rate by mini-sector, {main_comp} ({cfg.CASE_STUDY_EVENT})")
    fig.savefig("Images/track_deg_map.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 4.5))
    w = 0.8 / len(comps)
    for k in range(N):
        if classes[k] == "STRAIGHT":
            ax.axvspan(k - 0.5, k + 0.5, color="#dddddd", zorder=0)
    for i, c in enumerate(comps):
        ax.bar(np.arange(N) + (i - (len(comps) - 1) / 2) * w, fits[f"deg_rate_{c}"],
               width=w, color=COMP_COLORS.get(c), label=c)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xlabel("Mini-sector index (grey background = STRAIGHT, white = CORNER)")
    ax.set_ylabel("Fitted degradation rate (s per lap of tyre age)")
    ax.set_xticks(range(N))
    ax.legend(title="Compound")
    fig.savefig("Images/minisector_deg_bar.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    g = ms_df.groupby(["Driver", "Stint"]).size().reset_index(name="n")
    g = g.sort_values(["n", "Driver", "Stint"], ascending=[False, True, True]).iloc[0]
    st = ms_df[(ms_df["Driver"] == g["Driver"]) & (ms_df["Stint"] == g["Stint"])
               ].sort_values("LapNumber")
    pick = [st.iloc[1], st.iloc[-1]]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for row, col in zip(pick, ["#1f77b4", "#d62728"]):
        lp = sl[(sl["Driver"] == row["Driver"]) & (sl["LapNumber"] == row["LapNumber"])].iloc[0]
        car, _, rel = lap_t_rel(lp)
        ax.plot(rel, car["Speed"], color=col,
                label=f"lap {int(row['LapNumber'])}, tyre age {row['TyreLife']:.0f}")
    ax.set_xlabel("Relative distance around the lap")
    ax.set_ylabel("Speed (km/h)")
    ax.set_title(f"{g['Driver']}, stint {int(g['Stint'])}: second clean lap against last clean lap")
    ax.legend()
    fig.text(0.01, -0.04, "The difference mixes fuel burn and tyre wear. Shown for illustration only.",
             fontsize=9)
    fig.savefig("Images/speed_trace_early_vs_late.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(pd.DataFrame(out_rows).to_string())


if __name__ == "__main__":
    main()
