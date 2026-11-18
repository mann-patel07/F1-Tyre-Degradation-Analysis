"""Download race laps for other seasons with FastF1 into data/. Resumable.

Usage: python download_seasons.py [--season Y] [--refresh] [--check-2025]
"""
import os

os.environ.pop("F1_USERNAME", None)
os.environ.pop("F1_PASSWORD", None)

import argparse  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config as cfg  # noqa: E402
import expansion_config as xc  # noqa: E402
import fastf1  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
PART = DATA / "_partial"
REQUIRED = ["Driver", "LapNumber", "LapTime", "Stint", "Compound", "TyreLife",
            "TrackStatus", "IsAccurate", "PitInTime", "PitOutTime", "Time"]
OPTIONAL = ["Team", "FreshTyre", "Position", "Sector1Time", "Sector2Time",
            "Sector3Time", "Deleted"]
TIMEDELTA_COLS = ["LapTime", "Sector1Time", "Sector2Time", "Sector3Time"]


def log(msg: str) -> None:
    with open(HERE / "RUN_LOG.md", "a") as f:
        f.write(f"- {datetime.now(timezone.utc).date()}: {msg}\n")


def load_session(season: int, rnd: int):
    """Load one race with the rate-limit rule. Returns (session, error)."""
    waits, tries, last = 0, 0, None
    while True:
        try:
            s = fastf1.get_session(season, rnd, cfg.SESSION_TYPE)
            s.load(laps=True, telemetry=False, weather=True, messages=False)
            if len(s.laps) > 0:
                return s, None
            last = "empty laps"
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            if type(e).__name__ == "RateLimitExceededError":
                waits += 1
                if waits > xc.RATE_LIMIT_MAX_WAITS:
                    return None, f"rate limit, gave up after {waits - 1} waits"
                log(f"{season} round {rnd}: rate limit, wait {waits} of {xc.RATE_LIMIT_MAX_WAITS} ({xc.RATE_LIMIT_WAIT_S} s).")
                time.sleep(xc.RATE_LIMIT_WAIT_S)
                continue
        tries += 1
        if tries >= cfg.LOAD_RETRIES:
            return None, last
        time.sleep(cfg.RETRY_WAIT_S)


def laps_frame(session, rnd: int, event_name: str):
    """Build the lap table for one loaded race exactly as download_data.py does."""
    laps = session.laps
    missing = [c for c in REQUIRED if c not in laps.columns]
    if missing:
        return None, missing
    keep = REQUIRED + [c for c in OPTIONAL if c in laps.columns]
    df = pd.DataFrame(laps[keep]).copy()
    for c in TIMEDELTA_COLS:
        if c in df:
            df[c] = df[c].dt.total_seconds()
    df["is_pit_in_lap"] = df["PitInTime"].notna()
    df["is_pit_out_lap"] = df["PitOutTime"].notna()
    df["lap_end_s"] = df["Time"].dt.total_seconds()
    df = df.drop(columns=["PitInTime", "PitOutTime", "Time"])
    df["Round"] = rnd
    df["EventName"] = event_name
    return df, []


def weather_row(session, df: pd.DataFrame) -> dict:
    w = session.weather_data
    return {"total_laps": int(df["LapNumber"].max()), "mean_track_temp": float(w["TrackTemp"].mean()),
            "mean_air_temp": float(w["AirTemp"].mean()), "rain": bool(w["Rainfall"].any())}


def season_schedule(season: int):
    sched = fastf1.get_event_schedule(season, include_testing=False)
    return sched[sched["RoundNumber"] >= 1]


def csv_roundtrip(df: pd.DataFrame) -> pd.DataFrame:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return pd.read_csv(buf, dtype={"TrackStatus": str})


def download_season(season: int, refresh: bool) -> dict:
    DATA.mkdir(exist_ok=True)
    PART.mkdir(exist_ok=True)
    os.makedirs(str(HERE / cfg.CACHE_DIR), exist_ok=True)
    fastf1.Cache.enable_cache(str(HERE / cfg.CACHE_DIR))
    sched = season_schedule(season)
    wanted, loaded, failed, rows, frames = [], [], [], [], []
    for _, ev in sched.iterrows():
        rnd = int(ev["RoundNumber"])
        wanted.append(rnd)
        pcsv, pjson = PART / f"{season}_{rnd}.csv", PART / f"{season}_{rnd}.json"
        if pcsv.exists() and pjson.exists() and not refresh:
            frames.append(pd.read_csv(pcsv, dtype={"TrackStatus": str}))
            rows.append(json.loads(pjson.read_text()))
            loaded.append(rnd)
            continue
        s, err = load_session(season, rnd)
        row = {"Round": rnd, "EventName": ev["EventName"],
               "Date": str(ev["EventDate"].date()) if pd.notna(ev["EventDate"]) else ""}
        if s is None:
            row["load_status"] = "load_failed"
            failed.append({"round": rnd, "reason": err})
            log(f"{season} round {rnd} {ev['EventName']} load_failed: {err}")
            rows.append(row)
            continue
        df, missing = laps_frame(s, rnd, ev["EventName"])
        if df is None:
            row["load_status"] = "load_failed"
            failed.append({"round": rnd, "reason": f"missing required columns {missing}"})
            log(f"{season} round {rnd}: missing required columns {missing}; load_failed.")
            rows.append(row)
            continue
        row["load_status"] = "ok"
        row.update(weather_row(s, df))
        df.to_csv(pcsv, index=False)
        pjson.write_text(json.dumps(row))
        frames.append(df)
        rows.append(row)
        loaded.append(rnd)
        print("saved", season, rnd, ev["EventName"], flush=True)
    pd.concat(frames).to_csv(DATA / f"laps_{season}.csv", index=False)
    pd.DataFrame(rows).to_csv(DATA / f"races_{season}.csv", index=False)
    meta = {"season": season, "download_timestamp": datetime.now(timezone.utc).isoformat(),
            "fastf1_version": fastf1.__version__, "rounds_wanted": wanted,
            "rounds_loaded": loaded, "rounds_failed": failed}
    (DATA / f"metadata_{season}.json").write_text(json.dumps(meta, indent=2))
    return meta


def check_2025() -> None:
    rnd = xc.REGRESSION_ROUND_2025
    os.makedirs(str(HERE / cfg.CACHE_DIR), exist_ok=True)
    fastf1.Cache.enable_cache(str(HERE / cfg.CACHE_DIR))
    sched = season_schedule(2025)
    ev = sched[sched["RoundNumber"] == rnd].iloc[0]
    s, err = load_session(2025, rnd)
    assert s is not None, err
    df, missing = laps_frame(s, rnd, ev["EventName"])
    assert df is not None, missing
    new = csv_roundtrip(df)
    old = pd.read_csv(DATA / "laps_2025.csv", dtype={"TrackStatus": str})
    old = old[old["Round"] == rnd].reset_index(drop=True)
    assert len(new) == len(old), (len(new), len(old))
    assert list(new.columns) == list(old.columns), (list(new.columns), list(old.columns))
    for c in old.columns:
        a, b = old[c], new[c]
        if pd.api.types.is_numeric_dtype(a) and not pd.api.types.is_bool_dtype(a):
            assert np.allclose(a.to_numpy(float), b.to_numpy(float), rtol=0, atol=1e-9, equal_nan=True), c
        else:
            assert (a.fillna("<NA>").astype(str) == b.fillna("<NA>").astype(str)).all(), c
    print("CHECK-2025 PASSED:", len(new), "rows")
    log(f"Regression check 2025 round {rnd} through the new download code: PASSED ({len(new)} rows, same columns, numbers within 1e-9).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--check-2025", action="store_true")
    a = ap.parse_args()
    if a.check_2025:
        check_2025()
        return
    for season in ([a.season] if a.season else xc.REPLICATION_SEASONS):
        m = download_season(season, a.refresh)
        print(season, "loaded", len(m["rounds_loaded"]), "failed", len(m["rounds_failed"]), flush=True)


if __name__ == "__main__":
    main()
