"""Mini-sector telemetry for every dry 2025 race.

Usage:
  python run_telemetry_season.py --download   (needs a signed-in F1TV account, Stage 1b only)
  python run_telemetry_season.py --fit        (reads saved files only, no account, no network)
"""
import os

os.environ.pop("F1_USERNAME", None)
os.environ.pop("F1_PASSWORD", None)

import shutil  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config as cfg  # noqa: E402
import expansion_config as xc  # noqa: E402
import f1deg as F  # noqa: E402

HERE = Path(__file__).resolve().parent
N = cfg.N_MINISECTORS
MIN_FREE_BYTES = 5 * 1024 ** 3


def log(msg: str) -> None:
    with open(HERE / "RUN_LOG.md", "a") as f:
        f.write(f"- {datetime.now(timezone.utc).date()}: {msg}\n")


def lap_t_rel(lap):
    """Car data of one lap, elapsed time and relative distance."""
    car = lap.get_car_data().add_distance()
    t = (car["SessionTime"] - car["SessionTime"].iloc[0]).dt.total_seconds().to_numpy()
    rel = (car["Distance"] / car["Distance"].iloc[-1]).to_numpy()
    return car, t, rel


def _load_telemetry_session(fastf1, rnd):
    waits, tries, last = 0, 0, None
    while True:
        try:
            s = fastf1.get_session(cfg.SEASON, rnd, cfg.SESSION_TYPE)
            s.load(laps=True, telemetry=True, weather=False, messages=False)
            if len(s.laps) > 0:
                return s, None
            last = "empty"
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            if type(e).__name__ == "RateLimitExceededError":
                waits += 1
                if waits > xc.RATE_LIMIT_MAX_WAITS:
                    return None, "rate limit, gave up"
                log(f"Telemetry round {rnd}: rate limit, wait {waits} of {xc.RATE_LIMIT_MAX_WAITS}.")
                time.sleep(xc.RATE_LIMIT_WAIT_S)
                continue
        tries += 1
        if tries >= cfg.LOAD_RETRIES:
            return None, last
        time.sleep(cfg.RETRY_WAIT_S)


def _classes(ref):
    import telemetry_season as TS  # noqa: PLC0415
    rel = (ref["Distance"] / ref["Distance"].iloc[-1]).to_numpy()
    idx = np.minimum((rel * N).astype(int), N - 1)
    c2, c3 = TS.classify(rel, ref["Throttle"].to_numpy(), ref["Brake"].to_numpy(), N)
    return rel, idx, c2, c3


def download_race(fastf1, rnd, event, date, laps_all, fc):
    """Download and save one race. Returns the quality row (dict)."""
    base = {"round": rnd, "event": event}
    session, err = _load_telemetry_session(fastf1, rnd)
    if session is None:
        log(f"Telemetry round {rnd} {event}: load_failed: {err}")
        return {**base, "load_status": "load_failed"}
    raw = laps_all[laps_all["Round"] == rnd]
    clean, counts, _ = F.clean_laps(raw)
    assert counts["s7_not_slow"] == int(fc[fc["Round"] == rnd]["s7_not_slow"].iloc[0])
    clean, _ = F.apply_compound_minimum(clean)
    sl = session.laps
    rows, mism, ndrop = [], [], 0
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
        rows.append({"Driver": r["Driver"], "LapNumber": int(r["LapNumber"]), "Stint": int(r["Stint"]),
                     "Compound": r["Compound"], "TyreLife": r["TyreLife"], "lap_s": r["lap_s"],
                     **{f"ms_{k}": ms[k] for k in range(N)}})
    ms_df = pd.DataFrame(rows)
    d2, dropped2 = F.apply_compound_minimum(ms_df)
    if len(d2) == 0:
        log(f"Telemetry round {rnd} {event}: no kept laps.")
        return {**base, "load_status": "no_kept_laps"}
    ref_row = d2.loc[d2["lap_s"].idxmin()]
    m = sl[(sl["Driver"] == ref_row["Driver"]) & (sl["LapNumber"] == ref_row["LapNumber"])].iloc[0]
    ref = m.get_telemetry()
    rel, idx, c2, c3 = _classes(ref)
    rr = f"{rnd:02d}"
    for sub in ("minisectors_2025", "reference_laps_2025", "corners_2025"):
        (HERE / "data" / sub).mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"rel": rel, "X": ref["X"].to_numpy(), "Y": ref["Y"].to_numpy(),
                  "Speed": ref["Speed"].to_numpy(), "Throttle": ref["Throttle"].to_numpy(),
                  "Brake": ref["Brake"].to_numpy().astype(bool), "minisector": idx,
                  "class": [c2[i] for i in idx], "class3": [c3[i] for i in idx]}
                 ).to_csv(HERE / "data/reference_laps_2025" / f"{rr}.csv", index=False)
    try:
        ci = session.get_circuit_info()
        ci.corners[["X", "Y", "Number", "Letter", "Distance"]].to_csv(
            HERE / "data/corners_2025" / f"{rr}.csv", index=False)
    except Exception as e:  # noqa: BLE001
        log(f"Telemetry round {rnd} {event}: circuit info not saved: {e!r}")
    ms_df.to_csv(HERE / "data/minisectors_2025" / f"{rr}.csv", index=False)
    mm = np.array(mism, dtype=float)
    return {**base, "load_status": "ok", "clean_laps": len(clean), "kept": len(ms_df), "dropped": ndrop,
            "mismatch_mean": float(np.nanmean(mm)), "mismatch_median": float(np.nanmedian(mm)),
            "mismatch_max": float(np.nanmax(mm)), "compounds_dropped_after_mismatch": ";".join(dropped2)}


def download() -> None:
    free = shutil.disk_usage(HERE).free
    if free < MIN_FREE_BYTES:
        log(f"Telemetry download not started: only {free / 1e9:.1f} GB free.")
        print("not enough disk space")
        return
    import fastf1  # noqa: PLC0415
    os.makedirs(str(HERE / cfg.CACHE_DIR), exist_ok=True)
    fastf1.Cache.enable_cache(str(HERE / cfg.CACHE_DIR))
    races = pd.read_csv(HERE / "results/races.csv")
    r25 = pd.read_csv(HERE / "data/races_2025.csv").set_index("Round")
    laps_all = pd.read_csv(HERE / "data/laps_2025.csv", dtype={"TrackStatus": str})
    fc = pd.read_csv(HERE / "results/filter_counts.csv")
    used = races[races["status"] == "used"].sort_values("Round")
    bah = int(r25[r25["EventName"] == cfg.CASE_STUDY_EVENT].index[0])
    order = [bah] + [int(x) for x in used["Round"] if int(x) != bah]
    qpath = HERE / "results/telemetry_season_quality.csv"
    qrows = {int(r["round"]): r for r in pd.read_csv(qpath).to_dict("records")} if qpath.exists() else {}
    for rnd in order:
        rr = f"{rnd:02d}"
        event = r25.loc[rnd, "EventName"]
        if (HERE / "data/minisectors_2025" / f"{rr}.csv").exists():
            continue
        q = download_race(fastf1, rnd, event, r25.loc[rnd, "Date"], laps_all, fc)
        qrows[rnd] = q
        pd.DataFrame(sorted(qrows.values(), key=lambda x: x["round"])).to_csv(qpath, index=False)
        for d in (HERE / cfg.CACHE_DIR / "2025").glob(f"{r25.loc[rnd, 'Date']}_*"):
            shutil.rmtree(d, ignore_errors=True)
        print("telemetry saved", rnd, event, q["load_status"], flush=True)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("--download", "--fit"):
        print(__doc__)
        return
    if sys.argv[1] == "--download":
        download()
    else:
        import telemetry_season  # noqa: PLC0415
        telemetry_season.run_fit(HERE)


if __name__ == "__main__":
    main()
