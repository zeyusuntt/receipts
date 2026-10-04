"""Extract every fact the video shows from the run records, so nothing on screen is typed by hand.

Usage, from the repository root:
    PYTHONPATH=src .venv/bin/python video/scripts/extract_story.py \
        --repo . --out video/src/content/story.json

`--repo` is the checkout that holds the records (v2 P is committed; v1's launch-2 archive is
not). Runs are the ones chosen by the rule in docs/submission/2026-10-02-e0-script-and-readme.md,
section 5: the cold open is the first false done of A in P's order that a naive check would
accept; the featured run is the first task in P's order rejected on attempt 1, verified on appeal
and officially resolved.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from receipts.agent.worker import APPEAL_INSTRUCTION
from receipts.models import Verdict
from receipts.orchestrate import _appeal_evidence
from receipts.site import _display_command, _load_run, _pr_description

COLD_OPEN = "azure__walinuxagent-638"
FEATURED = "pyfilesystem__pyfilesystem2-462"
PILOT_V1 = "scikit-build__scikit-build-core-254"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


def _run_dir(repo: Path, record: dict[str, Any]) -> Path:
    run_dir = Path(record["run_dir"])
    return run_dir if run_dir.is_absolute() else repo / run_dir


def _predicates(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": p["id"], "passed": p["passed"], "evidence": p["evidence"]} for p in verdict["predicates"]]


def _predicate(attempt: dict[str, Any], predicate_id: str) -> dict[str, Any]:
    return next(p for p in attempt["predicates"] if p["id"] == predicate_id)


def _evidence_count(pattern: str, evidence: str, label: str) -> int:
    match = re.search(pattern, evidence)
    if not match:
        raise ValueError(f"cannot extract {label} from evidence: {evidence}")
    return int(match.group(1))


def _evidence_list_count(prefix: str, evidence: str, label: str) -> int:
    if not evidence.startswith(prefix):
        raise ValueError(f"cannot extract {label} from evidence: {evidence}")
    return len(evidence.removeprefix(prefix).split(", "))


def _attempt(run: Path, result: dict[str, Any], number: int) -> dict[str, Any]:
    attempt = result["attempts"][number - 1]
    verdict = _json(run / f"attempts/{number}/verdict.json")
    worker = attempt["worker"]
    return {
        "number": number,
        "said": _first_sentence(worker["summary"]),
        "summary": worker["summary"],
        "claims": worker["claims"],
        "verdict": verdict["status"],
        "predicates": _predicates(verdict),
        "claim_audit": verdict["claim_audit"],
        "claim_evidence": verdict["claim_evidence"],
        "witness_branch": attempt["witness_branch_id"],
        "dropped_paths": attempt.get("dropped_paths") or [],
        "filtered_sha256": attempt.get("filtered_sha256"),
        "verdict_model": verdict,
    }


def _cold_open(repo: Path) -> dict[str, Any]:
    record = _json(repo / f"pilot/v2-P/{COLD_OPEN}/record.json")
    run = _run_dir(repo, record)
    first = _attempt(run, _json(run / "result.json"), 1)
    failed = [p for p in first["predicates"] if not p["passed"]]
    first.pop("verdict_model")
    return {
        "instance": COLD_OPEN,
        "run_id": run.name,
        "said": first["said"],
        "claims": first["claims"],
        "witness_failed": failed,
        "naive_check_would_accept": record["attempts"][0]["naive_green"],
        "official_resolved": record["attempts"][0]["official_resolved"],
    }


def _featured(repo: Path) -> dict[str, Any]:
    record_path = repo / f"pilot/v2-P/{FEATURED}/record.json"
    record = _json(record_path)
    run = _run_dir(repo, record)
    site_run = _load_run(record_path, repo)
    result = _json(run / "result.json")
    inp = _json(run / "input.json")
    disclosure = _json(run / "disclosure.json")
    first, second = _attempt(run, result, 1), _attempt(run, result, 2)
    appeal = f"{_appeal_evidence(Verdict.model_validate(first['verdict_model']))}\n\n{APPEAL_INSTRUCTION}"
    for attempt in (first, second):
        attempt.pop("verdict_model")
    patch = (run / "attempts/2/filtered.diff").read_text(encoding="utf-8")
    receipts = {
        branch.parent.name: sum(1 for line in branch.read_text().splitlines() if line.strip())
        for branch in sorted((run / "branches").glob("*/receipts.jsonl"))
    }
    patch_files = [line.split(" b/", 1)[1] for line in patch.splitlines() if line.startswith("diff --git ")]
    agent_rows = [json.loads(line) for line in (run / "branches/agent1/receipts.jsonl").read_text().splitlines() if line.strip()]
    # Attempt 1 ends at its first diff receipt. Later rows belong to the appeal.
    first_diff = next(i for i, row in enumerate(agent_rows) if row["kind"] == "diff")
    agent_rows = agent_rows[:first_diff + 1]
    origin = datetime.fromisoformat(agent_rows[0]["started_at"])
    agent_steps = [{
        "receipt_id": row["receipt_id"], "seq": row["seq"], "kind": row["kind"],
        "display": _display_command(row),
        "offset_s": (datetime.fromisoformat(row["started_at"]) - origin).total_seconds(),
        "duration_s": row["duration_s"], "exit_code": row["exit_code"],
    } for row in agent_rows]
    witness_rows = [json.loads(line) for line in (run / "branches/w1/receipts.jsonl").read_text().splitlines() if line.strip()]
    sandbox_usage = _json(run / "cost.json")["sandbox_usage"]
    witness_operations = {
        branch: max(
            (operation for operation in sandbox_usage if operation["branch_id"] == branch),
            key=lambda operation: operation["duration_s"],
        )["operation_id"]
        for branch in ("w1", "w2")
    }
    r1 = _predicate(second, "R1_fail_to_pass")
    r2 = _predicate(second, "R2_pass_to_pass")
    r3 = _predicate(second, "R3_no_shrink")
    if not r3["passed"] or "skips unchanged" not in r3["evidence"]:
        raise ValueError(f"featured no-shrink evidence is not a pass: {r3['evidence']}")
    image_match = re.search(r":\d+-([0-9a-f]+)$", inp["source"]["image"])
    if not image_match:
        raise ValueError(f"cannot extract featured revision from image: {inp['source']['image']}")
    receipt = {
        "target_tests": _evidence_list_count("target tests passed: ", r1["evidence"], "target tests"),
        "kept_tests": _evidence_count(r"^(\d+) baseline-passing tests still pass$", r2["evidence"], "kept tests"),
        "collected_tests": _evidence_count(r"^all (\d+) baseline tests collected", r3["evidence"], "collected tests"),
        "removed_or_skipped": 0,
        "files_changed": len(patch_files),
        "test_files_changed": sum(1 for path in patch_files if path.startswith("tests/") or Path(path).name.startswith("test_")),
        "agent_steps": receipts["agent1"],
        "witness_steps": receipts[second["witness_branch"]],
        "attempts": [
            {"number": first["number"], "verdict": first["verdict"].lower()},
            {"number": second["number"], "verdict": "verified" if second["verdict"] == "PASS" else second["verdict"].lower()},
        ],
    }
    return {
        "instance": FEATURED,
        "run_id": run.name,
        "repo": "PyFilesystem/pyfilesystem2",
        "issue_title": inp["issue"].strip().splitlines()[0],
        "spec_tests": inp["spec_tests"],
        "image": inp["source"].get("image"),
        "revision": image_match.group(1),
        "checkpoint_id": result.get("checkpoint_id"),
        "model": disclosure["model"],
        "executor_kind": disclosure.get("executor_kind"),
        "attempts": [first, second],
        "appeal_text": appeal,
        "official": [a.get("official_resolved") for a in record["attempts"]],
        "agreement": [a.get("agreement") for a in record["attempts"]],
        "cost": record["cost"],
        "wall_time_s": record["wall_time_s"],
        "receipts_per_branch": receipts,
        "patch_files": patch_files,
        "patch_excerpt": patch.splitlines()[:40],
        "agent_steps": agent_steps,
        "replay_windows": [{"start_s": agent_steps[i]["offset_s"], "duration_s": 5} for i in [1, 10, 14, 23]],
        "witness_operations": witness_operations,
        "witness_receipts": [{"receipt_id": row["receipt_id"], "image_before": row["image_before"], "image_after": row["image_after"], "kind": row["kind"]} for row in witness_rows],
        "receipt": receipt,
        "pr_description": _pr_description(site_run),
    }


def _pilot_v1(repo: Path) -> dict[str, Any]:
    root = repo / f"pilot/aborted-2026-10-01-launch2/{PILOT_V1}"
    record = _json(root / "record.json")
    patch = next(root.glob("runs/*/attempts/1/filtered.diff")).read_text(encoding="utf-8")
    return {
        "instance": PILOT_V1,
        "launch": "v1 launch 2, commit ecc6dae (2026-10-01)",
        "gate": record["attempts"][0]["gate_status"],
        "official_resolved": record["attempts"][0]["official_resolved"],
        "shipped_files": [line.split(" b/", 1)[1] for line in patch.splitlines() if line.startswith("diff --git ")],
        "real_package": "src/scikit_build_core/",
        "real_build_package": "src/scikit_build_core/build/",
        "amendment": "PREREGISTRATION.md, Amendment 2 (2026-10-01)",
        "fix_commit": "3a5579b",
        "fix": "the trusted runner no longer adds the repository root to sys.path",
    }


def _numbers(repo: Path) -> dict[str, Any]:
    report = _json(repo / "pilot/v2-P/report.json")
    a, b = report["configuration_a"], report["configuration_b"]
    arm = _json(repo / "pilot/v2-arm-lightning/report.json")
    ran = [instance for instance in report["instances"] if instance["b_outcome"] != "infrastructure error"]
    receipt_files = []
    for instance in ran:
        run_dir = Path(instance["run_dir"])
        if not run_dir.is_absolute():
            run_dir = repo / run_dir
        receipt_files.extend(sorted((run_dir / "branches").glob("*/receipts.jsonl")))
    return {
        "headline": report["headline"],
        "tasks": report["ran_tasks"],
        "repos": len({re.sub(r"-\d+$", "", instance["instance_id"]) for instance in ran}),
        "scale": {
            "tokens": report["spend"]["final"]["tokens"],
            "sandboxes": len(receipt_files),
            "steps": sum(sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) for path in receipt_files),
        },
        "claimed": a["claimed_dones"],
        "false_dones": a["false_dones"],
        "false_done_pct": round(a["false_done_rate"]["value"] * 100, 1),
        "ci": [round(a["false_done_rate"]["lower_95"] * 100, 1), round(a["false_done_rate"]["upper_95"] * 100, 1)],
        "naive_check_false_dones": a["naive_green_false_dones"],
        "verified": b["verified_fixes"],
        "first_verdict": b["first_verdict"],
        "appeal": b["appeal"],
        "shipped_false_dones": b["shipped_false_dones"],
        "model_dollars_per_fix": round(b["cost_per_verified_fix"]["model_dollars"], 2),
        "model_spend": round(report["spend"]["all_runs"]["model_dollars"], 2),
        "gate_pass_officially_resolved": [
            report["agreement"]["matrix"]["PASS"]["resolved"],
            report["agreement"]["matrix"]["PASS"]["resolved"] + report["agreement"]["matrix"]["PASS"]["not_resolved"],
        ],
        "lightning_arm": {
            "tasks": arm["ran_tasks"],
            "verified": arm["configuration_b"]["verified_fixes"],
            "shipped_false_dones": arm["configuration_b"]["shipped_false_dones"],
            "model_dollars_per_fix": round(arm["configuration_b"]["cost_per_verified_fix"]["model_dollars"], 2),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    story = {
        "sources": {
            "records": "pilot/v2-P/ (committed), pilot/v2-arm-lightning/, pilot/aborted-2026-10-01-launch2/",
            "rule": "docs/submission/2026-10-02-e0-script-and-readme.md, section 5",
        },
        "cold_open": _cold_open(repo),
        "featured": _featured(repo),
        "pilot_v1": _pilot_v1(repo),
        "numbers": _numbers(repo),
    }
    # Approved display copy stays in the content source when facts are refreshed.
    if args.out.exists():
        previous = _json(args.out)
        if "presentation" in previous:
            story["presentation"] = previous["presentation"]
        if "media" in previous:
            story["media"] = previous["media"]
        for key in ("video_copy", "agent_steps"):
            if key in previous.get("sources", {}):
                story["sources"][key] = previous["sources"][key]
    text = json.dumps(story, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if any(prefix in text for prefix in ("/opt/homebrew", "/opt/receipts-", "/Users/", "/private/")):
        raise SystemExit("refusing to write a local or executor path into the video data")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out}: {len(text)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
