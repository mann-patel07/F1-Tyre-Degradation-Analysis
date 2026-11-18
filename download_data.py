"""Download 2025 race laps with FastF1 and save CSVs under data/."""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import fastf1
import pandas as pd

import config as C

REQUIRED = ["Driver", "LapNumber", "LapTime", "Stint", "Compound", "TyreLife",
            "TrackStatus", "IsAccurate", "PitInTime", "PitOutTime", "Time"]
OPTIONAL = ["Team", "FreshTyre", "Position", "Sector1Time", "Sector2Time",
            "Sector3Time", "Deleted"]
TIMEDELTA_COLS = ["LapTime", "Sector1Time", "Sector2Time", "Sector3Time"]


def log(msg: str) -> None:
    with open("RUN_LOG.md", "a") as f:
        f.write(f"- {datetime.now(timezone.utc).date()}: {msg}\n")


def load_race(rnd: int):
    last = None
    for attempt in range(C.LOAD_RETRIES):
        try:
            s = fastf1.get_session(C.SEASON, rnd, C.SESSION_TYPE)
            s.load(laps=True, telemetry=False, weather=True, messages=False)
            if len(s.laps) > 0:
                return s, None
            last = "empty laps"
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        if attempt < C.LOAD_RETRIES - 1:
            time.sleep(C.RETRY_WAIT_S)
    return None, last


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    out = Path("data")
    out.mkdir(exist_ok=True)
    if (out / "laps_2025.csv").exists() and not args.refresh:
        print("data exists; use --refresh to re-download")
        return
    Path(C.CACHE_DIR).mkdir(exist_ok=True)
    os.makedirs(C.CACHE_DIR, exist_ok=True)
    fastf1.Cache.enable_cache(C.CACHE_DIR)
    sched = fastf1.get_event_schedule(C.SEASON, include_testing=False)
    sched = sched[sched["RoundNumber"] >= 1]
    if len(sched) != 24:
        log(f"Schedule has {len(sched)} events, not 24; continuing.")
    all_laps, races, loaded, failed = [], [], [], []
    for _, ev in sched.iterrows():
        rnd = int(ev["RoundNumber"])
        s, err = load_race(rnd)
        row = {"Round": rnd, "EventName": ev["EventName"],
               "Date": str(ev["EventDate"].date()) if pd.notna(ev["EventDate"]) else "",
               "load_status": "ok" if s is not None else "load_failed"}
        if s is None:
            log(f"Round {rnd} {ev['EventName']} failed to load: {err}")
            failed.append(rnd)
            races.append(row)
            continue
        laps = s.laps
        missing = [c for c in REQUIRED if c not in laps.columns]
        if missing:
            print(f"HARD STOP 3: missing {missing}")
            log(f"HARD STOP 3: missing columns {missing}")
            sys.exit(1)
        keep = REQUIRED + [c for c in OPTIONAL if c in laps.columns]
        for c in OPTIONAL:
            if c not in laps.columns:
                log(f"Round {rnd}: optional column {c} missing.")
        df = pd.DataFrame(laps[keep]).copy()
        for c in TIMEDELTA_COLS:
            if c in df:
                df[c] = df[c].dt.total_seconds()
        df["is_pit_in_lap"] = df["PitInTime"].notna()
        df["is_pit_out_lap"] = df["PitOutTime"].notna()
        df["lap_end_s"] = df["Time"].dt.total_seconds()
        df = df.drop(columns=["PitInTime", "PitOutTime", "Time"])
        df["Round"] = rnd
        df["EventName"] = ev["EventName"]
        all_laps.append(df)
        w = s.weather_data
        row.update({
            "total_laps": int(df["LapNumber"].max()),
            "mean_track_temp": float(w["TrackTemp"].mean()),
            "mean_air_temp": float(w["AirTemp"].mean()),
            "rain": bool(w["Rainfall"].any()),
        })
        races.append(row)
        loaded.append(rnd)
        print(f"loaded round {rnd} {ev['EventName']}", flush=True)
    if not loaded:
        print("HARD STOP 2: no race loaded")
        log("HARD STOP 2: no race could be loaded.")
        sys.exit(1)
    pd.concat(all_laps).to_csv(out / "laps_2025.csv", index=False)
    pd.DataFrame(races).to_csv(out / "races_2025.csv", index=False)
    meta = {"download_timestamp": datetime.now(timezone.utc).isoformat(),
            "fastf1_version": fastf1.__version__,
            "rounds_loaded": loaded, "rounds_failed": failed}
    (out / "metadata.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
