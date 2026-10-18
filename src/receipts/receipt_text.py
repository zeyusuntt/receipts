"""Render one completed run as a portable Markdown verification receipt."""

from __future__ import annotations

import json
from typing import Any

from receipts.models import JunitSummary
from receipts.orchestrate import RunResult


_CHECKS = (
    ("R1_fail_to_pass", "Failing specification tests now pass"),
    ("R2_pass_to_pass", "Baseline-passing tests still pass"),
    ("R3_no_shrink", "The collected suite did not shrink"),
    ("R4_patch_scope", "The patch stayed in scope"),
    ("R5_provenance", "Agent and witness provenance is intact"),
    ("R7_no_shortcuts", "The patch takes no shortcut (no uncalled private helper, no stub)"),
    ("R8_review", "The independent Nemotron review raised no grounded objection"),
    ("R8_review_advisory", "Advisory: the independent Nemotron reviews raised no grounded objection"),
    ("R6_claim_audit", "The agent claim matches the record"),
)


def _cell(value: Any) -> str:
    text = str(value).replace("|", "\\|")
    return "<br>".join(part.strip() for part in text.splitlines())


def _setting(value: Any) -> str:
    if value is None:
        return "not set"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return str(value)


def _counts(summary: JunitSummary) -> str:
    return (
        f"{summary.n_passed} passed, {summary.n_failed} failed, "
        f"{summary.n_errors} errors, {summary.n_skipped} skipped, "
        f"{summary.collected} collected"
    )


def _joined(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _verdict_label(result: RunResult) -> str:
    if result.final_verdict.status == "PASS" and result.verified_fix:
        return "VERIFIED"
    if result.final_verdict.status == "ERROR":
        return "VERIFICATION ERROR"
    return "NO VERIFIED FIX"


def render(result: RunResult) -> str:
    """Return the complete PR-description receipt for a run."""

    lines = [
        "# Receipts verification",
        "",
        f"**Verdict: {_verdict_label(result)}**",
        "",
        f"- Gate status: `{result.final_verdict.status}`",
        f"- Issue: {_cell(result.input.issue)}",
        f"- Specification tests: {_cell(_joined(result.input.spec_tests))}",
        f"- Selected patch: `{result.selected_patch_path or 'none'}`",
        f"- Wall time: {result.wall_time_s:.3f} seconds",
        "",
        "## Verification checks",
        "",
        "| Check | Result | Evidence |",
        "|---|---|---|",
    ]

    predicate_by_id = {
        predicate.id: predicate for predicate in result.final_verdict.predicates
    }
    for check_id, title in _CHECKS:
        predicate = predicate_by_id.get(check_id)
        if predicate is None:
            state = "NOT EVALUATED"
            evidence = result.final_verdict.error or "No trustworthy evidence was available."
        else:
            state = "PASS" if predicate.passed else "FAIL"
            evidence = predicate.evidence
        lines.append(
            f"| `{check_id}` {title} | **{state}** | {_cell(evidence)} |",
        )

    lines.extend(
        [
            "",
            "## What the agent said and what the record shows",
            "",
            "| Attempt | What the agent said | Claims | Record |",
            "|---:|---|---|---|",
        ],
    )
    for attempt in result.attempts:
        claims = attempt.worker.claims
        if claims is None:
            rendered_claims = "none"
        else:
            rendered_claims = (
                f"tests_run={str(claims.tests_run).lower()}, "
                f"target_tests_pass={str(claims.target_tests_pass).lower()}, "
                f"full_suite_pass={str(claims.full_suite_pass).lower()}"
            )
        record = (
            f"{attempt.verdict.status}; claim audit {attempt.verdict.claim_audit}: "
            f"{attempt.verdict.claim_evidence}"
        )
        lines.append(
            f"| {attempt.number} | {_cell(attempt.worker.summary)} | "
            f"{_cell(rendered_claims)} | {_cell(record)} |",
        )

    lines.extend(
        [
            "",
            "## Base and patched runs",
            "",
            "| Run | Branch | Result |",
            "|---|---|---|",
        ],
    )
    for number, baseline_run in enumerate(result.baseline.runs, start=1):
        lines.append(f"| Baseline {number} | `base` | {_counts(baseline_run)} |")
    for attempt in result.attempts:
        lines.append(
            f"| Patched {attempt.number} | `{_cell(attempt.witness_branch_id)}` | "
            f"{attempt.verdict.status} |",
        )

    lines.extend(
        [
            "",
            "## Files changed and dropped",
            "",
            "| Attempt | Agent-reported changes | Dropped from witness patch |",
            "|---:|---|---|",
        ],
    )
    for attempt in result.attempts:
        claims = attempt.worker.claims
        changed = claims.files_changed if claims is not None else []
        lines.append(
            f"| {attempt.number} | {_cell(_joined(changed))} | "
            f"{_cell(_joined(attempt.dropped_paths))} |",
        )

    lines.extend(
        [
            "",
            "## Frozen tests and environment",
            "",
            "| Artifact | SHA-256 |",
            "|---|---|",
        ],
    )
    for path, digest in sorted(result.disclosure.test_digests.items()):
        lines.append(f"| Test `{_cell(path)}` | `{_cell(digest)}` |")
    for path, digest in sorted(result.disclosure.pytest_config_digests.items()):
        lines.append(f"| Pytest config `{_cell(path)}` | `{_cell(digest)}` |")
    lines.append(f"| Dependency lock `lock.txt` | `{result.disclosure.lock_sha256}` |")

    lines.extend(
        [
            "",
            "## Model and settings",
            "",
            f"- Receipts version: `{_cell(result.disclosure.receipts_version)}`",
            f"- Executor: `{_cell(result.disclosure.executor_kind)}`",
        ],
    )
    for name, value in sorted(result.disclosure.model.items()):
        lines.append(f"- {name}: `{_cell(_setting(value))}`")

    witnesses = ", ".join(
        f"attempt {attempt.number} `{attempt.witness_branch_id}`"
        for attempt in result.attempts
    ) or "none"
    lines.extend(
        [
            "",
            "## Lineage",
            "",
            (
                f"Snapshot receipt `{result.snapshot_receipt_id}` -> checkpoint "
                f"`{result.checkpoint_id}` -> agent branch `{result.agent_branch_id}`; "
                f"witnesses: {witnesses}."
            ),
            "",
            "## Cost",
            "",
            f"- Estimated dollars: ${float(result.cost.get('estimated_dollars') or 0):.6f}",
            f"- Sandbox seconds: {float(result.cost.get('sandbox_seconds') or 0):.3f}",
            f"- Pricing is an estimate: {str(bool(result.cost.get('pricing_is_estimate'))).lower()}",
            "",
            "| Model | Prompt tokens | Completion tokens | Reasoning tokens | Estimated dollars |",
            "|---|---:|---:|---:|---:|",
        ],
    )
    models = result.cost.get("models", {})
    for model_name, values in sorted(models.items()):
        dollars = values.get("estimated_dollars")
        rendered_dollars = "unknown" if dollars is None else f"${float(dollars):.6f}"
        lines.append(
            f"| `{_cell(model_name)}` | {values.get('prompt_tokens', 0)} | "
            f"{values.get('completion_tokens', 0)} | {values.get('reasoning_tokens', 0)} | "
            f"{rendered_dollars} |",
        )

    return "\n".join(lines) + "\n"


__all__ = ["render"]
