"""Run R7 on AERead trial tasks: each shipped patch on its start state, and each upstream fix.

R7 runs inside Receipts for runs made at or after the commit that adds it; this script is for
the runs made before it (the first eight) and for checking upstream fixes, which Receipts never
sees.

Usage (from the receipts repository):
  .venv/bin/python trials/aeread/scripts/r7_check_aeread.py WORK SCREENING_FILE REPLAYS [RUN_SUFFIX]
WORK holds aeread-clone/, the screening file and the replay folder.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")
from receipts.verify.shortcuts import find_shortcuts  # noqa: E402

WORK, SCREENING, REPLAYS = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
SUFFIX = sys.argv[4] if len(sys.argv) > 4 else ""
CLONE = WORK / "aeread-clone"

for line in (WORK / SCREENING).read_text().splitlines():
    record = json.loads(line)
    if not record.get("included"):
        continue
    commit, task = record["commit"], record["commit"][:12]
    replay = WORK / REPLAYS / f"aeread-{task}"
    attempts = Path("trials/aeread/runs") / f"{task}{SUFFIX}" / "attempts"
    shipped = "no run"
    if attempts.exists():
        last = max((p for p in attempts.iterdir() if p.is_dir()), key=lambda p: int(p.name))
        patch = (last / "filtered.diff").read_text() if (last / "filtered.diff").exists() else ""
        with tempfile.TemporaryDirectory(dir=WORK) as tmp:
            tree = Path(tmp) / "tree"
            shutil.copytree(replay / "start", tree, symlinks=True)
            applied = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=tree, input=patch,
                                     capture_output=True, text=True)
            shipped = ([f.model_dump() for f in find_shortcuts(patch, tree)]
                       if applied.returncode == 0 else "apply failed")
    upstream_patch = subprocess.run(["git", "diff", f"{commit}^", commit], cwd=CLONE,
                                    capture_output=True, text=True, check=True).stdout
    upstream = [f.model_dump() for f in find_shortcuts(upstream_patch, replay / "fixed")]
    print(json.dumps({"task": task + SUFFIX, "shipped": shipped, "upstream": upstream}), flush=True)
