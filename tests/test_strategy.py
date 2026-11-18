import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import strategy as S  # noqa: E402
import expansion_config as xc  # noqa: E402


def build(spec, n_laps=40, status=None, lap_time=None, pos_override=None, pit_flags=True):
    rows = []
    for d, s in spec.items():
        stops = s.get("stops", [])
        for lap in range(1, s.get("laps", n_laps) + 1):
            k = sum(1 for st in stops if st[0] < lap)
            comp = s.get("comp0", "SOFT") if k == 0 else stops[k - 1][1]
            start = 0 if k == 0 else stops[k - 1][0]
            age = lap if s.get("renumber") else lap - start
            pf = pit_flags and s.get("pit", True)
            st = (status or {}).get((d, lap), (status or {}).get(lap, "1"))
            pos = (pos_override or {}).get((d, lap), s["pos"])
            rows.append(dict(Driver=d, Team="T", LapNumber=lap, LapTime=(lap_time or {}).get((d, lap), 90.0),
                             Stint=k + 1, Compound=comp, TyreLife=age, TrackStatus=st, Position=pos,
                             lap_end_s=lap * 100 + s.get("off", s["pos"] * 30),
                             is_pit_in_lap=bool(pf and any(x[0] == lap for x in stops)),
                             is_pit_out_lap=bool(pf and k > 0 and stops[k - 1][0] == lap - 1)))
    return pd.DataFrame(rows)


def field(target_stops, extra=None, **kw):
    spec = {f"A{i}": dict(pos=i, stops=[(20, "HARD")]) for i in range(1, 5)}
    spec["T"] = dict(pos=5, stops=target_stops, **(extra or {}))
    return spec


def target_change(raw, stop=1):
    a = S.analyse_race(raw)
    return [c for c in a["changes"] if c["driver"] == "T" and c["stop"] == stop][0]


def test_boundaries():
    spec = {"A": dict(pos=1, stops=[(10, "HARD")]),
            "B": dict(pos=2, stops=[(5, "SOFT")], pit=False, renumber=True),
            "C": dict(pos=3, stops=[(7, "HARD")], pit=False)}
    raw = build(spec)
    raw.loc[(raw.Driver == "A") & (raw.LapNumber == 1), "is_pit_out_lap"] = True
    ch, passes, art = S.find_changes(raw)
    drivers = {c["driver"] for c in ch}
    assert drivers == {"A", "C"} and art == 1
    a = [c for c in ch if c["driver"] == "A"][0]
    assert (a["in_lap"], a["out_lap"], a["pit_stop"]) == (10, 11, True)
    c = [c for c in ch if c["driver"] == "C"][0]
    assert c["pit_stop"] is False
    assert passes == []


def test_pit_pass_without_change():
    raw = build({"A": dict(pos=1), "B": dict(pos=2)})
    raw.loc[(raw.Driver == "A") & (raw.LapNumber == 8), "is_pit_out_lap"] = True
    ch, passes, _ = S.find_changes(raw)
    assert ch == [] and len(passes) == 1 and passes[0]["lap"] == 8
    assert passes[0]["note"] == "pit lane pass with no tyre change recorded"


def test_tyre_data_incomplete():
    df = pd.DataFrame({"Stint": [1.0] * 100, "Compound": ["SOFT"] * 100})
    d6, d4 = df.copy(), df.copy()
    d6.loc[:5, "Stint"] = np.nan
    d4.loc[:3, "Compound"] = np.nan
    assert S.tyre_data_incomplete(d6) and not S.tyre_data_incomplete(d4)


def _ch(driver, stop, in_lap, status="1"):
    return {"driver": driver, "stop": stop, "in_lap": in_lap, "in_status": status}


def test_reference():
    drivers = {f"D{i}": {"completed": True, "n_changes": 1, "sequence": "SOFT>HARD"} for i in range(3)}
    drivers.update({f"E{i}": {"completed": True, "n_changes": 2, "sequence": "SOFT>MEDIUM>HARD"} for i in range(3)})
    drivers["X"] = {"completed": False, "n_changes": 1, "sequence": "SOFT>HARD"}
    changes = [_ch("D0", 1, 10), _ch("D1", 1, 20), _ch("D2", 1, 30), _ch("E0", 1, 100), _ch("X", 1, 5)]
    ref = S.reference_strategy(changes, drivers)
    assert ref["n_stops"] == 1  # tie 3 against 3 goes to the smaller
    assert ref["laps"][1] == 20.0
    assert ref["sequences"] == ["SOFT>HARD"]
    changes2 = [_ch("D0", 1, 10), _ch("D1", 1, 20, "4"), _ch("D2", 1, 30, "12")]
    assert S.reference_strategy(changes2, drivers)["laps"][1] is None
    d2 = {"A": {"completed": True, "n_changes": 1, "sequence": "S>H"}, "B": {"completed": True, "n_changes": 1, "sequence": "M>H"}}
    assert S.reference_strategy([], d2)["sequences"] == ["M>H", "S>H"]


def test_tags_reference_position():
    assert target_change(build(field([(22, "HARD")])))["tag_ON_REFERENCE"]
    assert target_change(build(field([(15, "HARD")])))["tag_EARLIER_THAN_REFERENCE"]
    assert target_change(build(field([(26, "HARD")])))["tag_LATER_THAN_REFERENCE"]
    c2 = target_change(build(field([(20, "HARD"), (35, "MEDIUM")])), stop=2)
    assert c2["tag_EXTRA_STOP"] and c2["tag_NO_REFERENCE"]
    raw = build({"A": dict(pos=1, stops=[(10, "HARD")]), "B": dict(pos=2, stops=[(20, "HARD")])})
    assert target_change(raw.assign(Driver=raw.Driver.replace({"A": "T"})), 1)["tag_NO_REFERENCE"]


def test_tags_status():
    st = lambda s: target_change(build(field([(22, "HARD")]), status={("T", 22): s}))
    assert st("41")["tag_SAFETY_CAR"]
    r = st("671")
    assert r["tag_VIRTUAL_SAFETY_CAR"] and not r["tag_SAFETY_CAR"]
    r = st("12")
    assert not r["tag_SAFETY_CAR"] and not r["tag_VIRTUAL_SAFETY_CAR"] and not r["tag_UNDERCUT_ATTEMPT"]
    assert r["primary"] == "ON_REFERENCE"
    assert not st("46")["tag_VIRTUAL_SAFETY_CAR"]


def test_red_flag_both_forms():
    assert target_change(build(field([(22, "HARD")]), status={("T", 22): "5"}))["tag_RED_FLAG"]
    spec = field([(22, "HARD")], extra=dict(pit=False))
    raw = build(spec, status={("T", 23): "5"})
    r = target_change(raw)
    assert r["tag_RED_FLAG"] and not r["tag_UNFLAGGED_CHANGE"] and not r["pit_stop"]


def test_weather_unknown_unflagged():
    assert target_change(build(field([(22, "INTERMEDIATE")])))["tag_WEATHER_TO_WET"]
    assert target_change(build(field([(22, "HARD")], extra=dict(comp0="INTERMEDIATE"))))["tag_WEATHER_TO_DRY"]
    assert target_change(build(field([(22, "WET")], extra=dict(comp0="INTERMEDIATE"))))["tag_WET_TO_WET"]
    r = target_change(build(field([(22, "UNKNOWN")])))
    assert r["tag_UNKNOWN_COMPOUND"] and not r["tag_WEATHER_TO_WET"]
    r = target_change(build(field([(22, "HARD")], extra=dict(pit=False))))
    assert r["tag_UNFLAGGED_CHANGE"] and r["primary"] in ("ON_REFERENCE", "UNFLAGGED_CHANGE")


def test_primary_order():
    assert target_change(build(field([(22, "HARD")]), status={("T", 22): "4"}))["primary"] == "SAFETY_CAR"
    r = target_change(build(field([(22, "INTERMEDIATE")]), status={("T", 22): "4"}))
    assert r["primary"] == "WEATHER_TO_WET"
    r = target_change(build(field([(22, "INTERMEDIATE")]), status={("T", 22): "45"}))
    assert r["primary"] == "RED_FLAG"


def test_cover_and_undercut_and_rivals():
    spec = field([(22, "HARD")])
    spec["A4"]["stops"] = [(21, "HARD")]
    spec["A4"]["off"] = 148
    r = target_change(build(spec))
    assert r["tag_COVER"] and r["rival_ahead"] == "A4" and abs(r["gap_ahead"] - 2.0) < 1e-9
    nan_pos = {("T", 21): np.nan}
    assert not target_change(build(spec, pos_override=nan_pos))["tag_COVER"]
    spec2 = field([(22, "HARD")])
    spec2["A4"]["stops"] = [(35, "HARD")]
    spec2["A4"]["off"] = 149
    r = target_change(build(spec2))
    assert r["tag_UNDERCUT_ATTEMPT"] and not r["tag_COVER"]
    assert not target_change(build(spec2, pos_override=nan_pos))["tag_UNDERCUT_ATTEMPT"]


def test_time_cost():
    spec = field([(22, "HARD")])
    for d in ("A1", "A2", "A3", "A4"):
        spec[d]["stops"] = []
    lt = {("T", 22): 110.0, ("T", 23): 100.0, ("A1", 22): 90.0, ("A1", 23): 90.0, ("A2", 22): 91.0,
          ("A2", 23): 91.0, ("A3", 22): 92.0, ("A3", 23): 92.0, ("A4", 22): 80.0, ("A4", 23): 80.0}
    raw = build(spec, lap_time=lt)
    assert abs(target_change(raw)["cost"] - (210.0 - 181.0)) < 1e-9
    spec["A4"]["stops"] = [(23, "HARD")]
    assert abs(target_change(build(spec, lap_time=lt))["cost"] - 28.0) < 1e-9
    del spec["A3"]
    del spec["A4"]
    assert target_change(build(spec, lap_time=lt))["cost"] is None


def test_position_change():
    spec = field([(22, "HARD")])
    po = {("T", 21): 5, ("T", 22 + 1 + xc.CYCLE_LAPS_AFTER): 3}
    assert target_change(build(spec, pos_override=po))["pos_change"] == 2


def _undercut_race(attacker_after, ahead_stops):
    spec = {"A1": dict(pos=1, stops=[(21, "HARD")] if ahead_stops else [], off=60),
            "T": dict(pos=2, stops=[(20, "HARD")], off=61)}
    po = {}
    for lap in range(22, 30):
        po[("T", lap)] = attacker_after
        po[("A1", lap)] = 3 - attacker_after
    return build(spec, pos_override=po)


def test_undercut_outcomes():
    ok = S.analyse_race(_undercut_race(1, True))
    t = [c for c in ok["changes"] if c["driver"] == "T"][0]
    assert t["tag_UNDERCUT_ATTEMPT"] and t["undercut_outcome"] == "SUCCEEDED"
    bad = S.analyse_race(_undercut_race(2, True))
    assert [c for c in bad["changes"] if c["driver"] == "T"][0]["undercut_outcome"] == "FAILED"
    nr = S.analyse_race(_undercut_race(1, False))
    assert [c for c in nr["changes"] if c["driver"] == "T"][0]["undercut_outcome"] == "NOT_RESOLVED"


def test_driver_labels():
    spec = {f"A{i}": dict(pos=i, stops=[(20, "HARD")]) for i in range(1, 5)}
    spec["COUNT"] = dict(pos=5, stops=[(20, "HARD"), (30, "MEDIUM")])
    spec["SEQ"] = dict(pos=6, stops=[(20, "MEDIUM")])
    spec["TIME"] = dict(pos=7, stops=[(32, "HARD")])
    spec["DNF"] = dict(pos=8, stops=[(20, "HARD")], laps=20)
    a = S.analyse_race(build(spec))
    lab = {r["driver"]: r for r in a["labels"]}
    assert lab["A1"]["label"] == "MATCHES_REFERENCE"
    assert lab["COUNT"]["label"] == "DIFFERS" and "stop count" in lab["COUNT"]["differences"]
    assert lab["SEQ"]["label"] == "DIFFERS" and "sequence" in lab["SEQ"]["differences"]
    assert lab["TIME"]["label"] == "DIFFERS" and "timing" in lab["TIME"]["differences"]
    assert lab["DNF"]["label"] == "DID_NOT_COMPLETE"


def test_sentences_have_no_banned_words():
    raws = [build(field([(22, "HARD")])), build(field([(22, "INTERMEDIATE")]), status={("T", 22): "4"}),
            build(field([(15, "HARD")], extra=dict(pit=False)))]
    for raw in raws:
        for c in S.analyse_race(raw)["changes"]:
            s = S.stop_sentence(c).lower()
            assert "consistent with" in s
            assert not any(w in s for w in S.BANNED)


def test_continuation_with_pit_flags_is_not_a_change():
    # see EXPLORATORY_ANALYSIS_PLAN_AMENDMENT_1.md
    raw = build({"A": dict(pos=1, stops=[(10, "SOFT")], renumber=True)})
    ch, passes, art = S.find_changes(raw)
    assert ch == [] and art == 0
    assert [p["kind"] for p in passes] == ["SAME_TYRE_CONTINUATION"]
    assert passes[0]["note"] == "stint number changed with pit flags set, but the same tyre continued"


def test_continuation_without_flags_is_still_an_artifact():
    raw = build({"A": dict(pos=1, stops=[(10, "SOFT")], renumber=True, pit=False)})
    ch, passes, art = S.find_changes(raw)
    assert ch == [] and passes == [] and art == 1


def test_same_compound_with_tyre_life_reset_is_still_a_change():
    raw = build({"A": dict(pos=1, stops=[(10, "SOFT")])})
    ch, passes, art = S.find_changes(raw)
    assert len(ch) == 1 and ch[0]["pit_stop"] and not any(p["kind"] == "SAME_TYRE_CONTINUATION" for p in passes)


def test_different_compound_with_tyre_life_plus_one_is_still_a_change():
    raw = build({"A": dict(pos=1, stops=[(10, "HARD")], renumber=True)})
    ch, passes, art = S.find_changes(raw)
    assert len(ch) == 1 and passes == [] and art == 0


def test_null_tyre_life_falls_back_to_old_rules():
    raw = build({"A": dict(pos=1, stops=[(10, "SOFT")], renumber=True)})
    raw.loc[(raw.Driver == "A") & (raw.LapNumber == 11), "TyreLife"] = np.nan
    ch, passes, art = S.find_changes(raw)
    assert len(ch) == 1
    raw2 = build({"A": dict(pos=1, stops=[(10, "SOFT")], renumber=True, pit=False)})
    raw2.loc[(raw2.Driver == "A") & (raw2.LapNumber == 11), "TyreLife"] = np.nan
    assert len(S.find_changes(raw2)[0]) == 1
