"""Watch a resumed v2 run past final infrastructure errors that were already reported.

Superseded by `receipts pilot watch`, which now acknowledges final infrastructure
errors present at startup and stops only on final markers for new instances. This
script remains because PREREGISTRATION-v2.md, Amendment 1 references it as the
frozen-code workaround for markers rewritten on every resume. It applies the same
pure `receipts.pilot.watch.decide` stop rules to a snapshot without the marker paths
that existed when it started. Every other stop condition, including model spend,
is unchanged.

Usage, from the repository root:
    PYTHONPATH=src .venv/bin/python scripts/v2-monitor.py PILOT_DIR PID --model-budget-usd 45
"""

from __future__ import annotations

import argparse
import os
import signal
import time
from pathlib import Path

from receipts.pilot.watch import (
    DirectorySnapshot,
    decide,
    newly_finished_lines,
    snapshot_directory,
)


def _without(snapshot: DirectorySnapshot, acknowledged: frozenset[str]) -> DirectorySnapshot:
    return DirectorySnapshot(
        files=tuple(f for f in snapshot.files if f.relative_path not in acknowledged),
    )


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pilot_dir", type=Path)
    parser.add_argument("pid", type=int)
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--model-budget-usd", type=float)
    args = parser.parse_args()

    snapshot = snapshot_directory(args.pilot_dir)
    acknowledged = frozenset(
        f.relative_path
        for f in snapshot.files
        if Path(f.relative_path).name == "final_infra_error.json"
    )
    print(f"acknowledged final infrastructure errors: {sorted(acknowledged)}", flush=True)
    _, seen = newly_finished_lines(snapshot, frozenset())
    while True:
        if not _pid_exists(args.pid):
            print("pilot process exited", flush=True)
            return 0
        reason = decide(
            _without(snapshot, acknowledged),
            model_budget_usd=args.model_budget_usd,
        )
        if reason is not None:
            try:
                os.kill(args.pid, signal.SIGTERM)
            except ProcessLookupError:
                print("pilot process exited", flush=True)
                return 0
            print(f"WATCHDOG: {reason}", flush=True)
            return 0
        time.sleep(args.interval)
        snapshot = snapshot_directory(args.pilot_dir)
        lines, seen = newly_finished_lines(snapshot, seen)
        for line in lines:
            print(line, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
