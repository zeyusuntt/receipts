"""Summarize AERead trial run folders: verdict, attempts, failed checks, R7, cost and time.

Usage: python summarize.py RUN_FOLDER... (each a folder under trials/aeread/runs)
Prints one JSON object per run.
"""
import json
import sys
from pathlib import Path

for folder in map(Path, sys.argv[1:]):
    result = json.loads((folder / "result.json").read_text())
    cost = json.loads((folder / "cost.json").read_text())
    attempts = []
    for attempt in sorted((p for p in (folder / "attempts").iterdir() if p.is_dir()), key=lambda p: int(p.name)):
        verdict = json.loads((attempt / "verdict.json").read_text()) if (attempt / "verdict.json").exists() else {}
        predicates = verdict.get("predicates", [])
        patch = (attempt / "filtered.diff").read_text() if (attempt / "filtered.diff").exists() else ""
        attempts.append({
            "attempt": int(attempt.name),
            "status": verdict.get("status"),
            "failed": [p["id"] for p in predicates if not p["passed"] and p["id"] != "R6_claim_audit"],
            "r7": next((p["evidence"] for p in predicates if p["id"] == "R7_no_shortcuts"), None),
            "claim_audit": verdict.get("claim_audit"),
            "patch_lines": sum(1 for line in patch.splitlines()
                               if line[:1] in "+-" and not line.startswith(("+++", "---"))),
        })
    status = (result.get("final_verdict") or {}).get("status")
    # cost.json's model totals already include the planner's call; planner_* repeat it as a detail.
    tokens = sum(m["prompt_tokens"] + m["completion_tokens"] for m in cost["models"].values())
    print(json.dumps({
        "run": folder.name,
        "verdict": {"PASS": "VERIFIED", "REJECTED": "REJECTED"}.get(status, status),
        "attempts": attempts,
        "tokens": tokens,
        "dollars": round(cost["estimated_dollars"], 3),
        "wall_s": round(result["wall_time_s"]),
    }))
