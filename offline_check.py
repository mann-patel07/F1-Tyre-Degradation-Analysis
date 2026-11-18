"""Prove that everything after the download runs offline and reproduces its results."""
import os
import runpy
import socket
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))
os.environ.pop("F1_USERNAME", None)
os.environ.pop("F1_PASSWORD", None)

DIRS = ["results/replication", "results/strategy", "results/pace", "results/telemetry_season"]
SCRIPTS = [("run_replication.py", []), ("run_strategy.py", []), ("run_pace.py", []),
           ("run_telemetry_season.py", ["--fit"]), ("run_links.py", []),
           ("check_consistency.py", [])]


def csvs():
    files = [p for d in DIRS for p in sorted((HERE / d).glob("*.csv"))]
    files.append(HERE / "results/links.csv")
    return files


def snapshot():
    return {str(p.relative_to(HERE)): pd.read_csv(p, dtype=str if False else None) for p in csvs()}


def same(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return False
    for c in a.columns:
        x, y = a[c], b[c]
        if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y) and not pd.api.types.is_bool_dtype(x):
            if not np.allclose(x.to_numpy(float), y.to_numpy(float), rtol=0, atol=1e-9, equal_nan=True):
                return False
        elif not (x.fillna("<NA>").astype(str).to_numpy() == y.fillna("<NA>").astype(str).to_numpy()).all():
            return False
    return True


def main() -> int:
    before = snapshot()
    attempts = []

    def blocked(*a, **k):
        attempts.append(1)
        raise RuntimeError("network blocked by offline_check")

    real_socket, real_cc = socket.socket, socket.create_connection

    class BlockedSocket(real_socket):
        def __init__(self, *a, **k):
            blocked()

    socket.socket = BlockedSocket
    socket.create_connection = blocked
    reason = None
    try:
        for name, argv in SCRIPTS:
            sys.argv = [name] + argv
            try:
                runpy.run_path(str(HERE / name), run_name="__main__")
                print(f"ok      {name} {' '.join(argv)}".rstrip())
            except SystemExit as e:
                if e.code not in (0, None):
                    reason = f"{name} exited with {e.code}"
                    break
                print(f"ok      {name} {' '.join(argv)}".rstrip())
            except BaseException as e:  # noqa: BLE001
                reason = f"{name} failed: {e!r}"
                print(f"FAILED  {name}")
                break
    finally:
        socket.socket, socket.create_connection = real_socket, real_cc
    if reason is None and attempts:
        reason = "a script tried to open a connection"
    if reason is None and "fastf1" in sys.modules:
        reason = "fastf1 is in sys.modules"
    if reason is None:
        after = snapshot()
        for k, v in before.items():
            if k not in after or not same(v, after[k]):
                reason = f"{k} changed"
                break
    if reason:
        print("OFFLINE CHECK FAILED:", reason)
        return 1
    print("OFFLINE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
