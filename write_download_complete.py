"""Write data/DOWNLOAD_COMPLETE.json after Stage 1. Reads saved files only. Never imports fastf1."""
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pandas as pd

import expansion_config as xc

HERE = Path(__file__).resolve().parent


def main():
    out = {"completed": datetime.now(timezone.utc).isoformat(), "fastf1_version": version("fastf1"), "seasons": {}}
    for s in xc.ALL_SEASONS:
        races = pd.read_csv(HERE / f"data/races_{s}.csv")
        meta = json.loads((HERE / ("data/metadata.json" if s == 2025 else f"data/metadata_{s}.json")).read_text())
        wanted = [int(x) for x in races["Round"]]
        failed = meta["rounds_failed"]
        loaded = [int(r) for r, st in zip(races["Round"], races["load_status"]) if st == "ok"]
        out["seasons"][str(s)] = {"races_wanted": wanted, "races_loaded": loaded, "races_failed": failed,
                                  "races_skipped": [], "note": "2025 was downloaded before the expansion" if s == 2025 else ""}
    q = pd.read_csv(HERE / "results/telemetry_season_quality.csv")
    saved = sorted(int(p.stem) for p in (HERE / "data/minisectors_2025").glob("*.csv"))
    rs = pd.read_csv(HERE / "results/races.csv")
    wanted = [int(r) for r in rs[rs["status"] == "used"]["Round"]]
    out["telemetry_2025"] = {"races_wanted": wanted, "races_saved": saved,
                             "races_failed": [{"round": int(r["round"]), "reason": r["load_status"]} for r in q.to_dict("records") if r["load_status"] != "ok"]}
    (HERE / "data/DOWNLOAD_COMPLETE.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
