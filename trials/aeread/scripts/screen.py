"""Screen the pre-registered AERead pool in order until enough tasks are included.

For each fix commit: build the start state (the parent plus the fix's test-file changes) as a
git repository, run the fix's changed test files at the start state and at the fix in
python:3.12-slim, and choose target tests by one of two rules:

  changed-functions  the changed test functions that fail at the start and pass at the fix
                     (the first eight tasks, PLAN.md);
  fail-to-pass       every test in the changed test files that fails at the start and passes
                     at the fix (Amendment 2, the held-out set).

--retarget recomputes the targets of tasks already screened from their saved screening logs,
without running anything (the in-sample rerun of the first eight, Amendment 2).

Usage:
  python screen.py WORK --rule fail-to-pass --replays replays-heldout --out screening-heldout.jsonl --start-position 11
  python screen.py WORK --rule fail-to-pass --replays replays --out screening-rerun.jsonl --retarget screening.jsonl

WORK holds aeread-clone/ (a clone of AERead) and aeread-pool-ordered.json (the pool in PLAN.md order).
"""
import argparse
import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

TEST_RE = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*\.py$")
GIT_ID = ["-c", "user.name=Zeyu Sun", "-c", "user.email=sunzeyu06@gmail.com"]


def git(clone, *args, cwd=None, check=True):
    return subprocess.run(["git", *args], cwd=cwd or clone, check=check, capture_output=True, text=True).stdout


def build_tree(clone, rev, dest):
    dest.mkdir(parents=True)
    archive = subprocess.run(["git", "archive", rev], cwd=clone, check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)


def changed_test_functions(clone, parent, fix, path):
    diff = git(clone, "diff", "-U0", parent, fix, "--", path)
    lines = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, count = int(m.group(1)), int(m.group(2) or 1)
        lines.update(range(start, start + max(count, 1)))
    try:
        tree = ast.parse(git(clone, "show", f"{fix}:{path}"))
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            span = set(range(node.lineno - len(node.decorator_list), (node.end_lineno or node.lineno) + 1))
            if span & lines:
                names.add(node.name)
    return names


def parse_rA(text):
    status = {}
    for m in re.finditer(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) (\S+)", text, re.M):
        if "::" in m.group(2):
            status[m.group(2)] = m.group(1)
    return status


def choose_targets(rec, out, changed, rule):
    """Fill in the targets and the verdict of a screening record from the screening log."""
    start_text = out.split("@@START", 1)[1].split("@@FIX", 1)[0] if "@@START" in out else ""
    start_status = parse_rA(start_text)
    fix_status = parse_rA(out.split("@@FIX", 1)[1]) if "@@FIX" in out else {}

    def counts(node):
        return rule == "fail-to-pass" or node.split("::")[-1].split("[")[0] in changed

    targets = {n for n, s in start_status.items()
               if s in ("FAILED", "ERROR") and counts(n) and fix_status.get(n) == "PASSED"}
    # A test file that cannot even be collected at the start state (for example it imports a
    # function the fix adds) reports "ERROR <file>" without test ids: every test in that file
    # that counts and passes at the fix fails at the start.
    errored_files = set(re.findall(r"^ERROR (\S+\.py)(?:\s|$)", start_text, re.M))
    for f in errored_files:
        targets |= {n for n, s in fix_status.items() if n.startswith(f + "::") and counts(n) and s == "PASSED"}
    rec.update(rule=rule, changed_functions=sorted(changed),
               start_failed=sorted(n for n, s in start_status.items() if s in ("FAILED", "ERROR")),
               collection_errors=sorted(errored_files), targets=sorted(targets))
    rec.pop("included", None)
    rec.pop("excluded", None)
    if not start_status and not errored_files:
        rec["excluded"] = "the changed test files did not run at the start state"
    elif not targets:
        rec["excluded"] = "no target test: none fails at the start state and passes at the fix"
    else:
        rec["included"] = True
    return rec


def screen(clone, replays, c, rule):
    fix, parent = c["h"], git(clone, "rev-parse", f"{c['h']}^").strip()
    tests = [p for p in git(clone, "diff", "--name-only", parent, fix).split() if p.endswith(".py") and TEST_RE.search(p)]
    rec = {"commit": fix, "parent": parent, "author": c["an"], "subject": c["s"], "test_files": tests}
    if not tests:
        rec["excluded"] = "no test file in the fix"
        return rec
    work = replays / f"aeread-{fix[:12]}"
    shutil.rmtree(work, ignore_errors=True)
    start, fixed = work / "start", work / "fixed"
    build_tree(clone, parent, start)
    build_tree(clone, fix, fixed)
    patch = git(clone, "diff", parent, fix, "--", *tests)
    (work / "test.patch").write_text(patch)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=start, check=True)
    subprocess.run(["git", "add", "-A"], cwd=start, check=True)
    subprocess.run(["git", *GIT_ID, "commit", "-q", "-m", f"AERead at upstream {parent[:12]} (the parent of fix {fix[:12]})"], cwd=start, check=True)
    applied = subprocess.run(["git", "apply", "--whitespace=nowarn", str(work / "test.patch")], cwd=start, capture_output=True, text=True)
    if applied.returncode != 0:
        rec["excluded"] = "start state cannot be built: " + applied.stderr.strip()[:200]
        return rec
    subprocess.run(["git", "add", "-A"], cwd=start, check=True)
    subprocess.run(["git", *GIT_ID, "commit", "-q", "-m", f"Add only the test changes from upstream fix {fix[:12]}"], cwd=start, check=True)
    rec["start_commit"] = git(clone, "rev-parse", "HEAD", cwd=start).strip()
    files = " ".join(tests)
    script = (
        "set -u; cp -r /start /w && cp -r /fixed /f && cd /w && "
        "pip install -q -e '.[dev]' > /tmp/pip.log 2>&1 || { echo INSTALL_FAILED; tail -20 /tmp/pip.log; exit 0; }; "
        f"python -m pytest -p no:cacheprovider -rA -q {files} > /tmp/start.txt 2>&1; echo '@@START'; cat /tmp/start.txt; "
        "cd /f && pip install -q -e '.[dev]' > /tmp/pip2.log 2>&1 || { echo FIX_INSTALL_FAILED; exit 0; }; "
        f"python -m pytest -p no:cacheprovider -rA -q {files} > /tmp/fix.txt 2>&1; echo '@@FIX'; cat /tmp/fix.txt"
    )
    run = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{start}:/start:ro", "-v", f"{fixed}:/fixed:ro", "python:3.12-slim", "sh", "-c", script],
        capture_output=True, text=True, timeout=1800,
    )
    out = run.stdout
    (work / "screen.log").write_text(out + run.stderr)
    if "INSTALL_FAILED" in out and "@@START" not in out:
        rec["excluded"] = "install fails in python:3.12-slim"
        return rec
    changed = set()
    for p in tests:
        changed |= changed_test_functions(clone, parent, fix, p)
    return choose_targets(rec, out, changed, rule)


def retarget(clone, replays, previous, out_path, rule):
    with out_path.open("w") as f:
        for line in previous.read_text().splitlines():
            rec = json.loads(line)
            if not rec.get("included"):
                continue
            log = (replays / f"aeread-{rec['commit'][:12]}" / "screen.log").read_text()
            changed = set()
            for p in rec["test_files"]:
                changed |= changed_test_functions(clone, rec["parent"], rec["commit"], p)
            rec = choose_targets(rec, log, changed, rule)
            f.write(json.dumps(rec) + "\n")
            print(rec["commit"][:12], rec.get("targets"), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--rule", choices=["changed-functions", "fail-to-pass"], required=True)
    parser.add_argument("--replays", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--start-position", type=int, default=1)
    parser.add_argument("--want", type=int, default=8)
    parser.add_argument("--retarget", help="a screening file whose included tasks get new targets from their logs")
    args = parser.parse_args()
    clone, replays, out_path = args.work / "aeread-clone", args.work / args.replays, args.work / args.out
    if args.retarget:
        retarget(clone, replays, args.work / args.retarget, out_path, args.rule)
        return
    order = json.loads((args.work / "aeread-pool-ordered.json").read_text())
    done = {}
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            r = json.loads(line)
            done[r["commit"]] = r
    included = sum(1 for r in done.values() if r.get("included"))
    for i, c in enumerate(order, 1):
        if i < args.start_position or c["h"] in done:
            continue
        if included >= args.want:
            break
        print(f"[{i}] screening {c['h'][:12]} {c['s'][:60]}", flush=True)
        try:
            rec = screen(clone, replays, c, args.rule)
        except Exception as exc:
            rec = {"commit": c["h"], "subject": c["s"], "excluded": f"screening error: {exc!r}"[:300]}
        rec["position"] = i
        with out_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        if rec.get("included"):
            included += 1
        print(f"    -> {'INCLUDED ' + str(rec.get('targets')) if rec.get('included') else 'excluded: ' + rec.get('excluded', '')}", flush=True)
    print(f"done: {included} included", flush=True)


if __name__ == "__main__":
    main()
