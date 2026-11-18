"""Pit strategy analysis (exploratory). Pure functions on lap tables."""
from collections import Counter
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config as cfg
import expansion_config as xc

PRIMARY_ORDER = ["RED_FLAG", "WEATHER_TO_WET", "WEATHER_TO_DRY", "WET_TO_WET", "SAFETY_CAR",
                 "VIRTUAL_SAFETY_CAR", "COVER", "UNDERCUT_ATTEMPT", "ON_REFERENCE", "EXTRA_STOP",
                 "EARLIER_THAN_REFERENCE", "LATER_THAN_REFERENCE", "UNFLAGGED_CHANGE", "UNKNOWN_COMPOUND",
                 "NO_REFERENCE"]
TAGS = PRIMARY_ORDER
BANNED = ["decided", "planned", "wanted", "chose to", "because"]


def has(status, digit: str) -> bool:
    """True if the status string contains the digit."""
    return isinstance(status, str) and digit in status


def is_green(status) -> bool:
    """True if the status string is exactly '1'."""
    return isinstance(status, str) and status == "1"


def compound_class(c) -> str:
    """dry, wet or unknown."""
    if isinstance(c, str) and c in cfg.DRY_COMPOUNDS:
        return "dry"
    if isinstance(c, str) and c in cfg.WET_COMPOUNDS:
        return "wet"
    return "unknown"


def tyre_data_incomplete(raw: pd.DataFrame) -> bool:
    """More than TYRE_DATA_MAX_MISSING of rows have a null Stint or null Compound."""
    if len(raw) == 0:
        return True
    miss = (raw["Stint"].isna() | raw["Compound"].isna()).mean()
    return bool(miss > xc.TYRE_DATA_MAX_MISSING)


def _str_status(v):
    return None if pd.isna(v) else str(v)


def build_lookup(raw: pd.DataFrame) -> dict:
    """Index laps by (driver, lap) and positions by lap."""
    lk = {}
    pos_at: Dict[int, Dict[int, str]] = {}
    for r in raw.itertuples(index=False):
        if pd.isna(r.LapNumber):
            continue
        n = int(r.LapNumber)
        lk[(r.Driver, n)] = {"time": r.LapTime, "pos": None if pd.isna(r.Position) else int(r.Position),
                             "end": r.lap_end_s, "status": _str_status(r.TrackStatus),
                             "pit_in": bool(r.is_pit_in_lap), "pit_out": bool(r.is_pit_out_lap)}
        if not pd.isna(r.Position):
            pos_at.setdefault(n, {}).setdefault(int(r.Position), r.Driver)
    return {"lap": lk, "pos_at": pos_at}


def find_changes(raw: pd.DataFrame):
    """Tyre changes, pit lane passes and renumbering artifacts for one race."""
    u = raw[raw["Stint"].notna() & raw["LapNumber"].notna()].sort_values(["Driver", "LapNumber"])
    changes, passes, artifacts = [], [], 0
    out_laps = set()
    for drv, g in u.groupby("Driver", sort=True):
        rows = list(g.itertuples(index=False))
        k = 0
        for a, b in zip(rows[:-1], rows[1:]):
            if a.Stint == b.Stint:
                continue
            same = (isinstance(a.Compound, str) and a.Compound == b.Compound)
            neither = (not bool(a.is_pit_in_lap)) and (not bool(b.is_pit_out_lap))
            life_ok = (not pd.isna(a.TyreLife)) and (not pd.isna(b.TyreLife)) and b.TyreLife == a.TyreLife + 1
            if same and life_ok:
                if neither:
                    artifacts += 1
                else:
                    out_laps.add((drv, int(b.LapNumber)))
                    passes.append({"driver": drv, "lap": int(b.LapNumber), "status": _str_status(b.TrackStatus),
                                   "kind": "SAME_TYRE_CONTINUATION",
                                   "note": "stint number changed with pit flags set, but the same tyre continued"})
                continue
            k += 1
            out_laps.add((drv, int(b.LapNumber)))
            changes.append({"driver": drv, "team": a.Team if hasattr(a, "Team") else None, "stop": k,
                            "in_lap": int(a.LapNumber), "out_lap": int(b.LapNumber),
                            "comp_before": a.Compound if isinstance(a.Compound, str) else None,
                            "comp_after": b.Compound if isinstance(b.Compound, str) else None,
                            "tyre_life": None if pd.isna(a.TyreLife) else float(a.TyreLife),
                            "pit_stop": bool(a.is_pit_in_lap) or bool(b.is_pit_out_lap),
                            "in_status": _str_status(a.TrackStatus), "out_status": _str_status(b.TrackStatus)})
    for r in u.itertuples(index=False):
        if int(r.LapNumber) >= 2 and bool(r.is_pit_out_lap) and (r.Driver, int(r.LapNumber)) not in out_laps:
            passes.append({"driver": r.Driver, "lap": int(r.LapNumber), "status": _str_status(r.TrackStatus),
                           "kind": "PIT_PASS", "note": "pit lane pass with no tyre change recorded"})
    return changes, passes, artifacts


def driver_summaries(raw: pd.DataFrame, changes: List[dict]) -> Dict[str, dict]:
    """Per driver: completed flag, change count, compound sequence, team."""
    race_max = raw["LapNumber"].max()
    out = {}
    u = raw[raw["Stint"].notna() & raw["LapNumber"].notna()].sort_values(["Driver", "LapNumber"])
    by_driver = {}
    for c in changes:
        by_driver.setdefault(c["driver"], []).append(c)
    for drv, g in raw.groupby("Driver"):
        mx = g["LapNumber"].max()
        ug = u[u["Driver"] == drv]
        first = ug["Compound"].iloc[0] if len(ug) and isinstance(ug["Compound"].iloc[0], str) else None
        ch = sorted(by_driver.get(drv, []), key=lambda c: c["stop"])
        seq = [ch[0]["comp_before"] if ch else first] + [c["comp_after"] for c in ch]
        team = g["Team"].mode().iloc[0] if "Team" in g and g["Team"].notna().any() else None
        out[drv] = {"completed": bool(mx >= xc.FINISH_FRACTION * race_max), "n_changes": len(ch),
                    "sequence": ">".join("?" if s is None else s for s in seq), "team": team}
    return out


def reference_strategy(changes: List[dict], drivers: Dict[str, dict]) -> dict:
    """What most completing drivers did under green. Not a team plan."""
    comp = {d: v for d, v in drivers.items() if v["completed"]}
    counts = Counter(v["n_changes"] for v in comp.values())
    if not counts:
        return {"n_stops": 0, "laps": {}, "qualifying": {}, "sequences": []}
    top = max(counts.values())
    n_stops = min(k for k, v in counts.items() if v == top)
    laps, qual = {}, {}
    for k in range(1, n_stops + 1):
        ins = [c["in_lap"] for c in changes if c["stop"] == k and c["driver"] in comp
               and comp[c["driver"]]["n_changes"] == n_stops and is_green(c["in_status"])]
        qual[k] = len(ins)
        laps[k] = float(np.median(ins)) if len(ins) >= xc.REF_MIN_STOPS else None
    seqs = Counter(v["sequence"] for v in comp.values() if v["n_changes"] == n_stops)
    stop_top = max(seqs.values())
    sequences = sorted(s for s, v in seqs.items() if v == stop_top)
    return {"n_stops": n_stops, "laps": laps, "qualifying": qual, "sequences": sequences}


def _rival(lk, driver, lap, delta):
    """Rival one position ahead (delta=-1) or behind (+1) at the end of lap-1."""
    me = lk["lap"].get((driver, lap - 1))
    if me is None or me["pos"] is None or me["end"] is None or pd.isna(me["end"]):
        return None, None
    rv = lk["pos_at"].get(lap - 1, {}).get(me["pos"] + delta)
    if rv is None or rv == driver:
        return None, None
    ro = lk["lap"].get((rv, lap - 1))
    if ro is None or ro["end"] is None or pd.isna(ro["end"]):
        return None, None
    return rv, float(abs(me["end"] - ro["end"]))


def time_cost(lk, changes_by_driver, drivers, driver, n) -> Optional[float]:
    """Stop cost against drivers who stayed out under the same conditions."""
    a, b = lk["lap"].get((driver, n)), lk["lap"].get((driver, n + 1))
    if a is None or b is None or pd.isna(a["time"]) or pd.isna(b["time"]):
        return None
    comp = []
    for d in drivers:
        if d == driver:
            continue
        x, y = lk["lap"].get((d, n)), lk["lap"].get((d, n + 1))
        if x is None or y is None or pd.isna(x["time"]) or pd.isna(y["time"]):
            continue
        if x["pit_in"] or x["pit_out"] or y["pit_in"] or y["pit_out"]:
            continue
        if any(c["in_lap"] in (n - 1, n, n + 1) for c in changes_by_driver.get(d, [])):
            continue
        comp.append(x["time"] + y["time"])
    if len(comp) < xc.MIN_COMPARISON_DRIVERS:
        return None
    return float((a["time"] + b["time"]) - np.median(comp))


def tag_changes(changes: List[dict], lk: dict, ref: dict, drivers: Dict[str, dict]) -> List[dict]:
    """Add tags, primary circumstance, rivals, cost, position change and undercut outcome."""
    by_driver = {}
    for c in changes:
        by_driver.setdefault(c["driver"], []).append(c)
    out = []
    for c in changes:
        n, drv = c["in_lap"], c["driver"]
        t = {k: False for k in TAGS}
        ins, outs = c["in_status"], c["out_status"]
        t["RED_FLAG"] = has(ins, "5") or has(outs, "5")
        if not c["pit_stop"] and not t["RED_FLAG"]:
            for m in range(n - 1, n + 3):
                r = lk["lap"].get((drv, m))
                if r is not None and has(r["status"], "5"):
                    t["RED_FLAG"] = True
                    break
        cb, ca = compound_class(c["comp_before"]), compound_class(c["comp_after"])
        if cb == "unknown" or ca == "unknown":
            t["UNKNOWN_COMPOUND"] = True
        elif cb == "dry" and ca == "wet":
            t["WEATHER_TO_WET"] = True
        elif cb == "wet" and ca == "dry":
            t["WEATHER_TO_DRY"] = True
        elif cb == "wet" and ca == "wet" and c["comp_before"] != c["comp_after"]:
            t["WET_TO_WET"] = True
        t["SAFETY_CAR"] = has(ins, "4")
        t["VIRTUAL_SAFETY_CAR"] = (has(ins, "6") or has(ins, "7")) and not has(ins, "4")
        ahead, gap_a = _rival(lk, drv, n, -1)
        behind, gap_b = _rival(lk, drv, n, +1)

        def changed_in(d, lo, hi):
            return any(lo <= x["in_lap"] <= hi for x in by_driver.get(d, []))
        cov = False
        for rv, g in ((ahead, gap_a), (behind, gap_b)):
            if rv is not None and g <= xc.COVER_GAP_S and changed_in(rv, n - xc.COVER_LOOKBACK_LAPS, n - 1):
                cov = True
        t["COVER"] = cov
        t["UNDERCUT_ATTEMPT"] = bool(ahead is not None and gap_a <= xc.UNDERCUT_GAP_S
                                     and not changed_in(ahead, n - xc.COVER_LOOKBACK_LAPS, n) and is_green(ins))
        k = c["stop"]
        ref_lap = ref["laps"].get(k) if k <= ref["n_stops"] else None
        diff = None
        if k > ref["n_stops"]:
            t["EXTRA_STOP"] = True
        if ref_lap is None:
            t["NO_REFERENCE"] = True
        else:
            diff = n - ref_lap
            if abs(diff) <= xc.REF_WINDOW_LAPS:
                t["ON_REFERENCE"] = True
            elif diff < 0:
                t["EARLIER_THAN_REFERENCE"] = True
            else:
                t["LATER_THAN_REFERENCE"] = True
        t["UNFLAGGED_CHANGE"] = (not c["pit_stop"]) and not t["RED_FLAG"]
        primary = next(x for x in PRIMARY_ORDER if t[x])
        cost = time_cost(lk, by_driver, drivers, drv, n)
        p0 = lk["lap"].get((drv, n - 1))
        p1 = lk["lap"].get((drv, n + 1 + xc.CYCLE_LAPS_AFTER))
        pchg = None
        if p0 and p1 and p0["pos"] is not None and p1["pos"] is not None:
            pchg = p0["pos"] - p1["pos"]
        outcome = None
        if t["UNDERCUT_ATTEMPT"]:
            outcome = "NOT_RESOLVED"
            resp = [x["in_lap"] for x in by_driver.get(ahead, []) if n < x["in_lap"] <= n + xc.UNDERCUT_RESPONSE_LAPS]
            if resp:
                m = min(resp)
                pa, pr = lk["lap"].get((drv, m + 1)), lk["lap"].get((ahead, m + 1))
                if pa and pr and pa["pos"] is not None and pr["pos"] is not None:
                    outcome = "SUCCEEDED" if pa["pos"] < pr["pos"] else ("FAILED" if pa["pos"] > pr["pos"] else "NOT_RESOLVED")
        out.append({**c, **{f"tag_{k2}": v for k2, v in t.items()}, "primary": primary, "ref_lap": ref_lap,
                    "laps_from_ref": diff, "cost": cost, "pos_change": pchg, "undercut_outcome": outcome,
                    "rival_ahead": ahead, "gap_ahead": gap_a, "rival_behind": behind, "gap_behind": gap_b,
                    "in_green": is_green(ins)})
    return out


def driver_labels(tagged: List[dict], drivers: Dict[str, dict], ref: dict) -> List[dict]:
    """MATCHES_REFERENCE, DIFFERS or DID_NOT_COMPLETE for every driver."""
    by = {}
    for c in tagged:
        by.setdefault(c["driver"], []).append(c)
    rows = []
    for d, v in sorted(drivers.items()):
        ch = sorted(by.get(d, []), key=lambda c: c["stop"])
        base = {"driver": d, "team": v["team"], "completed": v["completed"], "n_changes": v["n_changes"],
                "sequence": v["sequence"]}
        if not v["completed"]:
            rows.append({**base, "label": "DID_NOT_COMPLETE", "differences": "", "differing_stops": ""})
            continue
        diffs, stops = [], []
        if v["n_changes"] != ref["n_stops"]:
            diffs.append("stop count")
        if v["sequence"] not in ref["sequences"]:
            diffs.append("sequence")
        off = [c for c in ch if not c["tag_ON_REFERENCE"]]
        if off:
            diffs.append("timing")
            stops = [f"{c['stop']}:{c['primary']}" for c in off]
        rows.append({**base, "label": "DIFFERS" if diffs else "MATCHES_REFERENCE",
                     "differences": ";".join(diffs), "differing_stops": ";".join(stops)})
    return rows


def analyse_race(raw: pd.DataFrame) -> dict:
    """Full strategy analysis of one race lap table."""
    changes, passes, artifacts = find_changes(raw)
    drivers = driver_summaries(raw, changes)
    ref = reference_strategy(changes, drivers)
    lk = build_lookup(raw)
    tagged = tag_changes(changes, lk, ref, drivers)
    labels = driver_labels(tagged, drivers, ref)
    return {"changes": tagged, "passes": passes, "artifacts": artifacts, "drivers": drivers,
            "reference": ref, "labels": labels, "incomplete": tyre_data_incomplete(raw)}


def status_timeline(raw: pd.DataFrame) -> pd.DataFrame:
    """Set of status digits seen by any driver on each lap."""
    rows = []
    for n, g in raw[raw["LapNumber"].notna()].groupby("LapNumber"):
        digits = set()
        for s in g["TrackStatus"].dropna().astype(str):
            digits.update(ch for ch in s if ch.isdigit())
        rows.append({"lap": int(n), "statuses": "".join(sorted(digits))})
    return pd.DataFrame(rows)


def stop_sentence(row: dict) -> str:
    """One generated sentence per stop. Uses 'consistent with' for motive."""
    k, n = row["stop"], row["in_lap"]
    if row["tag_EXTRA_STOP"]:
        pos = "an extra stop beyond the reference count"
    elif row["tag_NO_REFERENCE"]:
        pos = "with no reference lap defined"
    elif row["tag_ON_REFERENCE"]:
        pos = "on the reference lap"
    elif row["tag_EARLIER_THAN_REFERENCE"]:
        pos = f"{abs(int(round(row['laps_from_ref'])))} laps earlier than the reference lap"
    else:
        pos = f"{abs(int(round(row['laps_from_ref'])))} laps later than the reference lap"
    if row["tag_SAFETY_CAR"]:
        ctx, why = "under a safety car", "a cheaper stop"
    elif row["tag_VIRTUAL_SAFETY_CAR"]:
        ctx, why = "under a virtual safety car", "a cheaper stop"
    elif row["tag_RED_FLAG"]:
        ctx, why = "under a red flag", "a change forced by the stoppage"
    elif row["tag_WEATHER_TO_WET"]:
        ctx, why = "with a switch to wet tyres", "reacting to the weather"
    elif row["tag_WEATHER_TO_DRY"]:
        ctx, why = "with a switch to dry tyres", "reacting to the weather"
    elif row["tag_WET_TO_WET"]:
        ctx, why = "with a switch between wet compounds", "no pattern this analysis can name"
    elif row["tag_UNKNOWN_COMPOUND"]:
        ctx, why = "with a compound missing from the data", "no pattern this analysis can name"
    elif row["tag_COVER"]:
        ctx, why = "after a nearby rival stopped", "covering that rival"
    elif row["tag_UNDERCUT_ATTEMPT"]:
        ctx, why = f"while within {row['gap_ahead']:.1f} seconds of the car ahead", "trying to pass that car through the stop"
    elif row["tag_UNFLAGGED_CHANGE"]:
        ctx, why = "with no pit lane lap recorded", "no pattern this analysis can name"
    else:
        ctx = "under green with no nearby rival stopping first"
        why = "the timing most of the field used" if row["tag_ON_REFERENCE"] else "no pattern this analysis can name"
    return f"Stop {k} on lap {n} was {pos} and came {ctx}, which is consistent with {why}."
