"""Run R7 over the 100-task experiment: every agent attempt, and the upstream PR's own fix.

The upstream fixes are correct by construction, so an R7 finding on one is a false positive.
For each task in pilot/v2-P: fetch the upstream PR diff with the GitHub CLI (the instance id ends
in the PR number), clone the repository at its base commit without history blobs, apply each
attempt's filtered patch and then the upstream diff with the official grader's flags, run
find_shortcuts on each, and delete the clone. Resumable.

Usage (from the receipts repository): .venv/bin/python trials/aeread/scripts/r7_check_swe.py WORK
Writes WORK/r7-check-swe.jsonl. Needs data/rebench-v2-python.jsonl (the SWE-rebench-V2 extract).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "src")
from receipts.verify.shortcuts import find_shortcuts  # noqa: E402

WORK = Path(sys.argv[1])
OUT = WORK / "r7-check-swe.jsonl"
CLONE = WORK / "swe-repo"
GOLD = WORK / "gold-diffs"
APPLY = ["apply", "-v", "--3way", "--recount", "--ignore-space-change", "--whitespace=nowarn", "-"]
GH_ENV = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
# The repository was renamed to a mirror without pull requests; its pull requests live here.
MOVED = {"rochacbruno/dynaconf": "dynaconf/dynaconf"}

instances = {p.name for p in Path("pilot/v2-P").iterdir() if p.is_dir()}
TASKS = {}
with open("data/rebench-v2-python.jsonl", encoding="utf-8") as rows:
    for line in rows:
        row = json.loads(line)
        if row["instance_id"] in instances:
            TASKS[row["instance_id"]] = (row["repo"], row["base_commit"])


def git(*args, cwd=None, inp=None, timeout=900):
    return subprocess.run(["git", *args], cwd=cwd, input=inp, capture_output=True, text=True, timeout=timeout)


def upstream_diff(instance, repo):
    GOLD.mkdir(parents=True, exist_ok=True)
    cached = GOLD / f"{instance}.diff"
    if cached.exists():
        return cached.read_text()
    number = instance.rsplit("-", 1)[1]
    fetched = subprocess.run(
        ["gh", "api", f"repos/{MOVED.get(repo, repo)}/pulls/{number}", "-H", "Accept: application/vnd.github.diff"],
        capture_output=True, text=True, env=GH_ENV, timeout=300,
    )
    if fetched.returncode != 0:
        return None
    cached.write_text(fetched.stdout)
    return fetched.stdout


def evaluate(patch, base):
    git("checkout", "-q", "-f", base, cwd=CLONE)
    git("clean", "-fdq", cwd=CLONE)
    if not patch.strip():
        return {"note": "empty patch", "findings": []}
    applied = git(*APPLY, cwd=CLONE, inp=patch)
    if applied.returncode != 0:
        return {"apply_ok": False, "findings": None}
    return {"apply_ok": True, "findings": [f.model_dump() for f in find_shortcuts(patch, CLONE)]}


done = set()
if OUT.exists():
    done = {json.loads(line)["task"] for line in OUT.read_text().splitlines() if line.strip()}

for instance, (repo, base) in sorted(TASKS.items()):
    if instance in done:
        continue
    finished = sorted((Path("pilot/v2-P") / instance / "runs").glob("*/result.json"))
    run = finished[-1].parent if finished else None
    official = {}
    if run and (run / "official" / "records.json").exists():
        for record in json.loads((run / "official" / "records.json").read_text()):
            if record.get("judgement") is not None:
                official[record["attempt"]] = record["judgement"]["resolved"]
    gold = upstream_diff(instance, repo)
    shutil.rmtree(CLONE, ignore_errors=True)
    clone = git("clone", "-q", "--filter=blob:none", "--no-checkout", f"https://github.com/{repo}.git", str(CLONE))
    checkout = git("checkout", "-q", base, cwd=CLONE) if clone.returncode == 0 else clone
    rows = []
    if checkout.returncode != 0:
        rows.append({"task": instance, "attempt": None, "error": (checkout.stderr or clone.stderr)[-300:]})
    else:
        if run is None:
            rows.append({"task": instance, "attempt": None, "skipped": "no completed run (infrastructure error)"})
        else:
            for attempt in sorted((p for p in (run / "attempts").iterdir() if p.is_dir()), key=lambda p: int(p.name)):
                patch = (attempt / "filtered.diff").read_text() if (attempt / "filtered.diff").exists() else ""
                verdict = json.loads((attempt / "verdict.json").read_text()) if (attempt / "verdict.json").exists() else {}
                rows.append({"task": instance, "attempt": int(attempt.name), "gate": verdict.get("status"),
                             "resolved": official.get(int(attempt.name)), **evaluate(patch, base)})
        if gold is None:
            rows.append({"task": instance, "attempt": "upstream", "error": "upstream PR diff not available"})
        else:
            rows.append({"task": instance, "attempt": "upstream", **evaluate(gold, base)})
    shutil.rmtree(CLONE, ignore_errors=True)
    with OUT.open("a") as out:
        for row in rows:
            out.write(json.dumps(row) + "\n")
    print(instance, [(row.get("attempt"), row.get("gate"), row.get("resolved"),
                      len(row["findings"]) if row.get("findings") is not None
                      else row.get("error") or row.get("skipped") or "apply failed") for row in rows], flush=True)
print("done", flush=True)
