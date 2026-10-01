from datetime import datetime, timezone

import pytest

from receipts.models import (
    Baseline, Branch, ChangedFile, Checkpoint, Claims, DiffSummary,
    JunitSummary, PredicateResult, Receipt, Verdict,
)


def _receipt(**overrides) -> Receipt:
    base = dict(
        receipt_id="b1-1", seq=1, branch_id="b1", kind="command", cmd="echo hi",
        exit_code=0, stdout_tail="hi\n", stderr_tail="", stdout_sha256="abc",
        started_at=datetime(2026, 9, 30, tzinfo=timezone.utc), duration_s=0.01,
        timed_out=False, image_before="img-0", image_after="img-1",
    )
    base.update(overrides)
    return Receipt(**base)


def test_receipt_round_trips_through_json():
    r = _receipt(
        log_path="/executor/logs/b1-1.log",
        junit=JunitSummary(passed=["t.py::a"], failed=["t.py::b"], errors=[], skipped=[]),
    )
    again = Receipt.model_validate_json(r.model_dump_json())
    assert again == r
    assert again.log_path == "/executor/logs/b1-1.log"
    assert again.junit.failed == ["t.py::b"]


def test_receipt_patch_and_snapshot_fields():
    applied = _receipt(kind="apply", patch_sha256="patch-digest")
    diff = _receipt(kind="diff", dropped_paths=["tests/conftest.py"])
    snapshot = _receipt(snapshot_sha="a" * 40)
    assert applied.patch_sha256 == "patch-digest"
    assert diff.dropped_paths == ["tests/conftest.py"]
    assert snapshot.snapshot_sha == "a" * 40
    assert _receipt().dropped_paths == []


def test_receipt_kinds_are_restricted():
    with pytest.raises(ValueError):
        _receipt(kind="opinion")


def test_junit_summary_derived_values():
    j = JunitSummary(passed=["a", "b"], failed=["c"], errors=[], skipped=["d"])
    assert j.collected == 4 and j.n_passed == 2 and j.n_failed == 1 and j.n_skipped == 1 and j.n_errors == 0
    assert j.all_ids() == {"a", "b", "c", "d"}
    assert j.outcome("c") == "failed" and j.outcome("zzz") == "missing"


def test_diff_summary_categories_are_restricted():
    ChangedFile(path="src/x.py", added=1, deleted=0, category="source")
    with pytest.raises(ValueError):
        ChangedFile(path="src/x.py", added=1, deleted=0, category="mystery")


def test_verdict_shape():
    v = Verdict(
        branch_id="b1", status="REJECTED",
        predicates=[PredicateResult(id="R1_fail_to_pass", passed=False, evidence="t.py::b failed")],
        claim_audit="contradicted", claim_evidence="claimed green; own run had 1 failed",
    )
    assert v.failed_predicate_ids() == ["R1_fail_to_pass"]


def test_baseline_and_claims_construct():
    b = Baseline(runs=[], run_receipt_ids=[], collected_ids=["t.py::a", "t.py::b"], skipped_ids=[],
                 protected=["t.py::a"], unstable=[], target=["t.py::b"])
    c = Claims(tests_run=True, target_tests_pass=True, full_suite_pass=False, files_changed=["src/x.py"])
    assert b.target == ["t.py::b"] and c.files_changed == ["src/x.py"]
    checkpoint = Checkpoint(id="img-0", parent=None)
    assert checkpoint.digest is None
    assert Checkpoint(id="img-1", parent="img-0", digest="abc").digest == "abc"
    Branch(id="b1", run_id="run-1", head="img-0", origin="img-0")
