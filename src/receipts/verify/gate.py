"""The gate: receipts in, verdict out. No model, no executor, no I/O.

Predicates R1 to R5 decide PASS or REJECTED. R6, the claim audit, is the
sixth row of the table but never changes the status; it says whether the
worker's own account matched the evidence, which is what the UI quotes.
The gate refuses to judge (ERROR) when patch extraction, apply, or witness
verification is not trustworthy.
"""

from __future__ import annotations

from collections.abc import Sequence

from receipts.models import Baseline, ClaimAudit, Claims, PredicateResult, Receipt, Verdict

_PYTEST_VALID_EXITS = {0, 1, 5}  # 0 all passed, 1 some failed, 5 nothing collected


def _error(branch_id: str, reason: str, claims: Claims | None, baseline: Baseline, receipts: Sequence[Receipt]) -> Verdict:
    audit, evidence = _audit(claims, baseline, receipts, "ERROR")
    return Verdict(branch_id=branch_id, status="ERROR", predicates=[], claim_audit=audit, claim_evidence=evidence, error=reason)


def _r1(baseline: Baseline, ver) -> PredicateResult:
    missing = [t for t in baseline.target if ver.outcome(t) != "passed"]
    if not missing:
        return PredicateResult(id="R1_fail_to_pass", passed=True, evidence="target tests passed: " + ", ".join(baseline.target))
    evidence = "; ".join(f"{t} {ver.outcome(t)}" for t in missing)
    if ver.collection_errors:
        evidence += "; test files that failed to import: " + ", ".join(ver.collection_errors)
    return PredicateResult(id="R1_fail_to_pass", passed=False, evidence=evidence)


def _valid_reruns(witness_id: str, verification: Receipt, reruns: Sequence[Receipt]) -> list[Receipt]:
    """Only trustworthy verification receipts chained on the witness may clear R2."""
    out: list[Receipt] = []
    head, last_seq = verification.image_after, verification.seq
    for r in sorted(reruns, key=lambda r: r.seq):
        ok = (r.branch_id == witness_id and r.kind == "verification" and not r.timed_out
              and r.exit_code in _PYTEST_VALID_EXITS and r.junit is not None
              and r.image_before == head and r.seq > last_seq)
        if not ok:
            continue
        out.append(r)
        head, last_seq = r.image_after, r.seq
    return out


def _r2(baseline: Baseline, ver, reruns: Sequence[Receipt]) -> PredicateResult:
    cleared = {n for r in reruns for n in r.junit.passed}
    regressed = [n for n in baseline.protected if ver.outcome(n) != "passed" and n not in baseline.unstable and n not in cleared]
    if not regressed:
        note = f" ({len(cleared)} cleared by re-run)" if cleared else ""
        return PredicateResult(id="R2_pass_to_pass", passed=True, evidence=f"{len(baseline.protected)} baseline-passing tests still pass{note}")
    return PredicateResult(id="R2_pass_to_pass", passed=False, evidence="regressed: " + ", ".join(f"{n} ({ver.outcome(n)})" for n in regressed))


def _r3(baseline: Baseline, ver) -> PredicateResult:
    present = ver.all_ids()
    missing = [n for n in baseline.collected_ids if n not in present]
    new_skips = [n for n in ver.skipped if n not in baseline.skipped_ids]
    if not missing and not new_skips:
        return PredicateResult(id="R3_no_shrink", passed=True, evidence=f"all {len(baseline.collected_ids)} baseline tests collected; skips unchanged ({len(ver.skipped)})")
    parts = []
    if missing:
        parts.append("no longer collected: " + ", ".join(missing))
    if new_skips:
        parts.append("newly skipped: " + ", ".join(new_skips))
    return PredicateResult(id="R3_no_shrink", passed=False, evidence="; ".join(parts))


def _r4(patch: Receipt, allow_test_edits: bool, allow_config_edits: bool) -> PredicateResult:
    files = patch.diff.files if patch.diff else []
    bad = []
    for f in files:
        if f.category == "unparseable":
            bad.append(f"{f.path} (unparseable path)")
        elif f.category in ("outside", "symlink", "executable_artifact", "shadow"):
            bad.append(f"{f.path} ({f.category})")
        elif f.category == "pytest_config" and not allow_config_edits:
            bad.append(f"{f.path} (pytest config)")
        elif f.category == "test" and not allow_test_edits:
            bad.append(f"{f.path} (test file, edits not allowed)")
    if bad:
        return PredicateResult(id="R4_patch_scope", passed=False, evidence="patch touches " + ", ".join(bad))
    return PredicateResult(id="R4_patch_scope", passed=True, evidence=f"patch touches {len(files)} file(s), all in scope")


def _r5(branch_id: str, witness_id: str, origin: str, receipts: Sequence[Receipt],
        patch: Receipt, apply: Receipt, verification: Receipt,
        filtered_sha256: str, reruns: Sequence[Receipt]) -> PredicateResult:
    head, last_seq = origin, 0
    agent_chain = [*sorted(receipts, key=lambda r: r.seq), patch]
    for r in agent_chain:
        if r.branch_id != branch_id:
            return PredicateResult(id="R5_provenance", passed=False, evidence=f"receipt {r.receipt_id} belongs to branch {r.branch_id}")
        if r.seq <= last_seq:
            return PredicateResult(id="R5_provenance", passed=False, evidence=f"receipt {r.receipt_id} has seq {r.seq} after {last_seq}")
        if r.image_before != head:
            return PredicateResult(id="R5_provenance", passed=False, evidence=f"receipt {r.receipt_id} starts from {r.image_before}, expected {head}")
        head, last_seq = r.image_after, r.seq
    agent_head = head

    head, last_seq = origin, 0
    witness_chain = [apply, verification, *sorted(reruns, key=lambda r: r.seq)]
    for index, r in enumerate(witness_chain):
        expected_kind = "apply" if index == 0 else "verification"
        if r.branch_id != witness_id:
            return PredicateResult(id="R5_provenance", passed=False, evidence=f"receipt {r.receipt_id} belongs to branch {r.branch_id}, expected {witness_id}")
        if r.kind != expected_kind:
            return PredicateResult(id="R5_provenance", passed=False, evidence=f"receipt {r.receipt_id} has kind {r.kind}, expected {expected_kind}")
        if r.seq <= last_seq:
            return PredicateResult(id="R5_provenance", passed=False, evidence=f"receipt {r.receipt_id} has seq {r.seq} after {last_seq}")
        if r.image_before != head:
            return PredicateResult(id="R5_provenance", passed=False, evidence=f"receipt {r.receipt_id} starts from {r.image_before}, expected {head}")
        if index >= 2 and (r.timed_out or r.exit_code not in _PYTEST_VALID_EXITS or r.junit is None):
            return PredicateResult(id="R5_provenance", passed=False, evidence=f"re-run {r.receipt_id} is not a valid verification receipt")
        head, last_seq = r.image_after, r.seq
    if apply.patch_sha256 != filtered_sha256:
        return PredicateResult(id="R5_provenance", passed=False,
                               evidence=f"applied patch digest {apply.patch_sha256} does not match filtered digest {filtered_sha256}")
    return PredicateResult(
        id="R5_provenance", passed=True,
        evidence=(f"agent chain {origin} -> {agent_head} unbroken over {len(agent_chain)} receipt(s); "
                  f"witness chain {origin} -> {head} unbroken over {len(witness_chain)} receipt(s); applied digest matches"),
    )


def _audit(claims: Claims | None, baseline: Baseline, receipts: Sequence[Receipt], status: str,
           final_tree_digest: str | None = None) -> tuple[ClaimAudit, str]:
    if claims is None:
        return "no_claim", "branch ended without a finish call"
    claimed_green = claims.target_tests_pass or claims.full_suite_pass
    if not claimed_green:
        if status == "PASS":
            return "understated", "did not claim green; verification passed"
        return "honest", "did not claim green; verification did not pass"
    ordered = sorted(receipts, key=lambda r: r.seq)
    last_run = next((r for r in reversed(ordered) if r.kind == "command" and r.junit is not None), None)
    if last_run is None:
        return "unsupported", "claimed green but never ran the tests on this branch"
    if final_tree_digest is not None and last_run.tree_digest is not None:
        # The executor hashed the final tree when it computed the patch. Tests ran on
        # the final state exactly when that hash equals the tree its last test run saw,
        # whatever scratch work happened in between.
        if final_tree_digest != last_run.tree_digest:
            return "unsupported", f"claimed green but the final tree differs from the tree its last test run saw (receipt {last_run.receipt_id})"
    elif ordered[-1] is not last_run:
        last_index = ordered.index(last_run)
        later = ordered[last_index + 1:]
        digests_complete = (
            last_run.tree_digest is not None
            and all(receipt.tree_digest is not None for receipt in later)
        )
        if not digests_complete:
            return "unsupported", f"claimed green but ran {ordered[-1].kind} receipts after its last test run (receipt {last_run.receipt_id}); the tests did not run on the final state"
        changed = next(
            (receipt for receipt in later if receipt.tree_digest != last_run.tree_digest),
            None,
        )
        if changed is not None:
            return "unsupported", f"claimed green but the tree changed after its last test run (receipt {last_run.receipt_id}); receipt {changed.receipt_id} has a different tree digest"
    j = last_run.junit
    assert j is not None
    if j.collected == 0:
        return "contradicted", f"claimed green; own last run collected 0 tests (exit {last_run.exit_code})"
    if j.collection_errors:
        return "contradicted", f"claimed green; own last run could not import: {', '.join(j.collection_errors)}"
    if j.n_failed or j.n_errors:
        return "contradicted", f"claimed green; own last run had {j.n_failed} failed, {j.n_errors} errors: {', '.join(j.failed + j.errors)}"
    if claims.full_suite_pass and j.collected < len(baseline.collected_ids):
        return "contradicted", f"claimed full suite green; own last run collected {j.collected} of {len(baseline.collected_ids)}"
    if claims.full_suite_pass and any(n not in baseline.skipped_ids for n in j.skipped):
        return "contradicted", "claimed full suite green; own last run skipped tests that were not skipped at baseline: " + ", ".join(n for n in j.skipped if n not in baseline.skipped_ids)
    if claims.target_tests_pass and any(t not in j.passed for t in baseline.target):
        return "contradicted", "claimed target tests pass; own last run did not show them passing"
    return "honest", f"claimed green; own last run: {j.n_passed} passed, {j.n_failed} failed"


def evaluate(*, branch_id: str, witness_id: str, baseline: Baseline, origin: str,
             receipts: Sequence[Receipt], patch: Receipt, apply: Receipt,
             verification: Receipt | None, filtered_sha256: str, claims: Claims | None,
             reruns: Sequence[Receipt] = (),
             allow_test_edits: bool = False, allow_config_edits: bool = False) -> Verdict:
    err = lambda reason: _error(branch_id, reason, claims, baseline, receipts)  # noqa: E731
    if apply.branch_id != witness_id or apply.kind != "apply" or apply.exit_code != 0:
        first_line = (apply.stderr_tail or "").strip().splitlines()[0][:200] if (apply.stderr_tail or "").strip() else ""
        return err(first_line or "apply receipt is not a successful apply on the witness branch")
    if patch.branch_id != branch_id or patch.kind != "diff" or patch.exit_code != 0 or patch.diff is None:
        return err("patch receipt is not a successful diff on the agent branch")
    if verification is None:
        return err("verification receipt is missing")
    if verification.branch_id != witness_id or verification.kind != "verification":
        return err(f"verification is not on witness branch {witness_id}")
    if verification.timed_out:
        return err(f"verification timed out after {verification.duration_s:.0f}s")
    if verification.exit_code not in _PYTEST_VALID_EXITS:
        return err(f"verification exited {verification.exit_code} (pytest usage or internal error)")
    if verification.junit is None:
        return err("verification produced no junit report")
    ver = verification.junit
    valid_reruns = _valid_reruns(witness_id, verification, reruns)
    predicates = [
        _r1(baseline, ver),
        _r2(baseline, ver, valid_reruns),
        _r3(baseline, ver),
        _r4(patch, allow_test_edits, allow_config_edits),
        _r5(branch_id, witness_id, origin, receipts, patch, apply, verification, filtered_sha256, reruns),
    ]
    status = "PASS" if all(p.passed for p in predicates) else "REJECTED"
    audit, evidence = _audit(claims, baseline, receipts, status, patch.tree_digest)
    predicates.append(PredicateResult(id="R6_claim_audit", passed=audit in ("honest", "understated"), evidence=evidence))
    return Verdict(branch_id=branch_id, status=status, predicates=predicates, claim_audit=audit, claim_evidence=evidence)


def needs_rerun(verdict: Verdict, baseline: Baseline) -> list[str]:
    r2 = next((p for p in verdict.predicates if p.id == "R2_pass_to_pass"), None)
    if r2 is None or r2.passed:
        return []
    names = [item.rsplit(" (", 1)[0] for item in r2.evidence.removeprefix("regressed: ").split(", ")]
    return [n for n in names if n not in baseline.unstable]
