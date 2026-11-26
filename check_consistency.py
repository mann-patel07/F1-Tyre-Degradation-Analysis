"""Check that numbers and paths in README.md match results/."""
import re
from pathlib import Path

import pandas as pd

readme = Path("README.md").read_text() + "\n" + Path("MORE_RESULTS.md").read_text()
s = pd.read_csv("results/summary.csv").set_index("metric")["value"]
cv = pd.read_csv("results/corner_vs_straight.csv").set_index("compound")
q = pd.read_csv("results/telemetry_quality.csv").iloc[0]
n = int(s["validation_eligible_races"])
checks = 0


def need(pattern, expected, fmt):
    global checks
    m = re.search(pattern, readme)
    assert m, f"pattern not found: {pattern}"
    got = [float(g) for g in m.groups()]
    exp = [round(float(e), fmt) for e in expected]
    assert got == exp, (pattern, got, exp)
    checks += 1


need(r"Validation-eligible races: (\d+) of (\d+) \((\d+) wet, (\d+) failed", [n, s["races_in_season"], s["wet_races"], s["failed_loads"]], 0)
need(r"D1 = (-?[\d.]+) s \(indicative interval (-?[\d.]+) to (-?[\d.]+)\)", [s["D1"], s["D1_lo"], s["D1_hi"]], 3)
need(r"beat the model without it in (\d+) of (\d+)", [s["races_M1_beat_M0"], n], 0)
need(r"Pooled test MAE: (-?[\d.]+) s without degradation, (-?[\d.]+) s with", [s["pooled_test_MAE_M0"], s["pooled_test_MAE_M1"]], 3)
need(r"D2 = (-?[\d.]+) s \(indicative interval (-?[\d.]+) to (-?[\d.]+)\), and the quadratic model beat the linear one in (\d+) of",
     [s["D2"], s["D2_lo"], s["D2_hi"], s["races_M2_beat_M1"]], 3)
for m in ["M0", "M1", "M2"]:
    need(rf"\| {m} \| (-?[\d.]+) \| (-?[\d.]+) \| (-?[\d.]+) \|",
         [s[f"pooled_test_MAE_{m}"], s[f"pooled_test_RMSE_{m}"], s[f"pooled_test_bias_{m}"]], 3)
need(r"(\d+) of (\d+) clean laps passed", [q["kept"], q["clean_laps"]], 0)
for c in ["SOFT", "MEDIUM", "HARD"]:
    need(rf"For {c}, corner mini-sectors carry (-?[\d.]+) percent of the fitted degradation and straight mini-sectors carry (-?[\d.]+) percent",
         [100 * cv.loc[c, "corner_share"], 100 * cv.loc[c, "straight_share"]], 1)

P = pd.read_csv("results/replication/pooled_summary.csv").set_index("metric")["value"]
T = pd.read_csv("results/telemetry_season/summary.csv").set_index("metric")
ss = pd.read_csv("results/strategy/season_summary.csv")
ss["season"] = ss["season"].astype(str)
AL = ss[ss["season"] == "ALL"]
tsn = pd.read_csv("results/pace/team_season.csv")


def g(group, metric):
    return AL[(AL["group"] == group) & (AL["metric"] == metric)].iloc[0]


need(r"R1 = (-?[\d.]+) s \(indicative interval (-?[\d.]+) to (-?[\d.]+)\) over (\d+) races pooled\. The linear degradation model beat the model without it in (\d+) of",
     [P["R1"], P["R1_lo"], P["R1_hi"], P["races_pooled"], P["races_M1_beat_M0"]], 3)
for y in (2022, 2023, 2024):
    need(rf"{y}: D1 = (-?[\d.]+) \((-?[\d.]+) to (-?[\d.]+)\)", [P[f"{y}_D1"], P[f"{y}_D1_lo"], P[f"{y}_D1_hi"]], 3)
verdict = Path("results/replication/verdict.txt").read_text().strip()
assert verdict in readme, "verdict sentence differs from verdict.txt"
checks += 1
t1 = T.loc["T1"]
m = re.search(r"T1 = (-?[\d.]+) \(indicative interval (-?[\d.]+) to (-?[\d.]+)\) over (\d+) races\. G was above zero in (\d+) races", readme)
assert m
got = [float(x) for x in m.groups()]
exp = [round(t1["value"], 6), round(t1["lo"], 6), round(t1["hi"], 6), int(T.loc["races_used", "value"]), int(T.loc["races_G_positive", "value"])]
assert got == exp, (got, exp)
checks += 1
sc = g("SAFETY_CAR", "share_of_changes")["value"] + g("VIRTUAL_SAFETY_CAR", "share_of_changes")["value"]
gd, us, dif = g("SAFETY_CAR", "green_minus_median_stop_cost_s"), g("undercut", "success_share_of_resolved"), g("drivers", "share_differs")
oc = {k: int(g(k, "undercut_count")["value"]) for k in ("SUCCEEDED", "FAILED", "NOT_RESOLVED")}
need(r"primary circumstance of (-?[\d.]+) percent of tyre changes\. The median stop cost is (-?[\d.]+) s under green and (-?[\d.]+) s under a safety car, and green minus safety car is (-?[\d.]+) s \(indicative interval (-?[\d.]+) to (-?[\d.]+)\)",
     [round(100 * sc, 1), g("green", "median_stop_cost_s")["value"], g("SAFETY_CAR", "median_stop_cost_s")["value"], gd["value"], gd["lo"], gd["hi"]], 3)
need(r"Undercut attempts: (\d+) succeeded, (\d+) failed, (\d+) not resolved, a success share of (-?[\d.]+) percent of (\d+) resolved\. (-?[\d.]+) percent of completing",
     [oc["SUCCEEDED"], oc["FAILED"], oc["NOT_RESOLVED"], round(100 * us["value"], 1), us["n"], round(100 * dif["value"], 1)], 1)
top = tsn[tsn["season"] == 2025].sort_values("rank").head(3)
for _, r in top.iterrows():
    need(rf"{int(r['rank'])}\. {re.escape(r['team'])}: (-?[\d.]+) s per lap \(indicative interval (-?[\d.]+) to (-?[\d.]+), (\d+) races\)", [r["mean_pace"], r["lo"], r["hi"], r["races"]], 3)

# stint split section (added after the first version)
ST = pd.read_csv("results/stint_split/summary.csv").set_index(["scope", "group", "metric"])["value"]


def stint_cell(scope, group):
    return f"{ST[scope, group, 'D1']:.3f} ({ST[scope, group, 'D1_lo']:.3f} to {ST[scope, group, 'D1_hi']:.3f})"


for label, grp in (("Continuing", "continuing"), ("New stint", "new")):
    need_row = f"| {label} | {stint_cell('2025', grp)} | {stint_cell('2022-2024 pooled', grp)} |"
    assert need_row in readme, f"stint split table row differs: {need_row}"
    checks += 1
need(r"Continuing laps are (-?[\d.]+) percent of the 2025 test laps and (-?[\d.]+) percent of the pooled",
     [100 * ST["2025", "continuing", "share_of_test_laps"], 100 * ST["2022-2024 pooled", "continuing", "share_of_test_laps"]], 1)
need(r"it is small: (-?[\d.]+) s in 2025, where", [ST["2025", "continuing", "D1"]], 3)
need(r"where the lower end of the interval is (-?[\d.]+), and", [ST["2025", "continuing", "D1_lo"]], 4)
need(r"and (-?[\d.]+) s pooled\. New-stint", [ST["2022-2024 pooled", "continuing", "D1"]], 3)
need(r"larger D1 in both, (-?[\d.]+) s and (-?[\d.]+) s",
     [ST["2025", "new", "D1"], ST["2022-2024 pooled", "new", "D1"]], 3)
need(r"above zero in (\d+) of (\d+) races in 2025 and in (\d+) of (\d+) races pooled",
     [ST["2025", "continuing", "D1_above_zero"], ST["2025", "continuing", "races"],
      ST["2022-2024 pooled", "continuing", "D1_above_zero"], ST["2022-2024 pooled", "continuing", "races"]], 0)
assert Path("MORE_RESULTS.md").exists() and Path("UPGRADE_PLAN.md").exists()
checks += 1

for path in set(re.findall(r"`([^`\s]+\.(?:py|md|csv|json|ipynb|txt|png))`", readme)) | set(re.findall(r"\((Images/[^)]+)\)", readme)):
    if "/" in path or Path(path).suffix:
        assert Path(path).exists() or path in ("data/laps_2025.csv",), f"missing {path}"
for p in ["data/laps_2025.csv", "data/races_2025.csv", "data/metadata.json", "results", "Images", "tests/test_f1deg.py"]:
    assert Path(p).exists(), p
print(f"consistency check passed ({checks} numeric checks)")
