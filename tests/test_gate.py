from datetime import datetime, timezone

import pytest

from receipts.models import Baseline, ChangedFile, DiffSummary, Receipt
from receipts.verify.gate import evaluate, needs_rerun
from tests.fixtures import gate_cases


@pytest.mark.parametrize("case", gate_cases.CASES, ids=[c.__name__ for c in gate_cases.CASES])
def test_gate_fixture(case):
    kwargs, (status, failed_ids, audit) = case()
    v = evaluate(**kwargs)
    assert v.status == status, v
    assert v.failed_predicate_ids() == failed_ids, v
    assert v.claim_audit == audit, v
    assert [p.id for p in v.predicates] == ["R1_fail_to_pass", "R2_pass_to_pass", "R3_no_shrink", "R4_patch_scope", "R5_provenance", "R6_claim_audit"]
    for p in v.predicates:
        assert p.evidence, p


@pytest.mark.parametrize("case", gate_cases.ERROR_CASES, ids=[c.__name__ for c in gate_cases.ERROR_CASES])
def test_gate_refuses_to_judge_broken_verification(case):
    kwargs = case()
    v = evaluate(**kwargs)
    assert v.status == "ERROR" and v.error and v.predicates == []
    # The audit still reflects what the worker said, even when verification broke.
    assert v.claim_audit == ("no_claim" if kwargs["claims"] is None else "honest")


def test_unsupported_when_any_command_follows_the_last_test_run():
    kwargs, _ = gate_cases.honest_pass()
    c = gate_cases.Chain()
    c.head = kwargs["receipts"][-1].image_after
    c.seq = kwargs["receipts"][-1].seq
    late = c.add("command", cmd="rm -rf tests/test_calc.py", exit_code=0)
    kwargs["receipts"] = [*kwargs["receipts"], late]
    kwargs["patch"].receipt_id = f"b1-{late.seq + 1}"
    kwargs["patch"].seq = late.seq + 1
    kwargs["patch"].image_before = late.image_after
    kwargs["patch"].image_after = f"b1-img{late.seq + 1}"
    v = evaluate(**kwargs)
    assert v.claim_audit == "unsupported" and "after its last test run" in v.claim_evidence


def _append_receipt_after_last_test(kwargs, *, kind, tree_digest, **fields):
    last_test = kwargs["receipts"][-1]
    last_test.tree_digest = "a" * 64
    c = gate_cases.Chain()
    c.head = last_test.image_after
    c.seq = last_test.seq
    late = c.add(kind, tree_digest=tree_digest, **fields)
    kwargs["receipts"] = [*kwargs["receipts"], late]
    kwargs["patch"].receipt_id = f"b1-{late.seq + 1}"
    kwargs["patch"].seq = late.seq + 1
    kwargs["patch"].image_before = late.image_after
    kwargs["patch"].image_after = f"b1-img{late.seq + 1}"


def test_read_only_command_after_last_test_run_keeps_green_claim_honest():
    kwargs, _ = gate_cases.honest_pass()
    _append_receipt_after_last_test(
        kwargs,
        kind="command",
        cmd="cat calc/__init__.py",
        exit_code=0,
        tree_digest="a" * 64,
    )

    verdict = evaluate(**kwargs)

    assert verdict.claim_audit == "honest"


def test_source_write_after_last_test_run_makes_green_claim_unsupported():
    kwargs, _ = gate_cases.honest_pass()
    _append_receipt_after_last_test(
        kwargs,
        kind="write",
        path="calc/__init__.py",
        exit_code=0,
        tree_digest="b" * 64,
    )

    verdict = evaluate(**kwargs)

    assert verdict.claim_audit == "unsupported"
    assert "tree changed after its last test run" in verdict.claim_evidence


def _append_undigested_scratch_work(kwargs, *, final_tree_digest):
    """Daytona-style: plain commands and writes after the last test run carry no
    tree digest; the patch receipt carries the digest of the final tree."""
    last_test = kwargs["receipts"][-1]
    last_test.tree_digest = "a" * 64
    c = gate_cases.Chain()
    c.head = last_test.image_after
    c.seq = last_test.seq
    scratch = [
        c.add("write", path="scratch_check.py", exit_code=0, tree_digest=None),
        c.add("command", cmd="python scratch_check.py", exit_code=0, tree_digest=None),
        c.add("command", cmd="rm -f scratch_check.py", exit_code=0, tree_digest=None),
    ]
    kwargs["receipts"] = [*kwargs["receipts"], *scratch]
    last = scratch[-1]
    kwargs["patch"].receipt_id = f"b1-{last.seq + 1}"
    kwargs["patch"].seq = last.seq + 1
    kwargs["patch"].image_before = last.image_after
    kwargs["patch"].image_after = f"b1-img{last.seq + 1}"
    kwargs["patch"].tree_digest = final_tree_digest


def test_reverted_scratch_work_after_last_test_run_stays_honest_when_final_tree_matches():
    kwargs, _ = gate_cases.honest_pass()
    _append_undigested_scratch_work(kwargs, final_tree_digest="a" * 64)

    verdict = evaluate(**kwargs)

    assert verdict.claim_audit == "honest", verdict.claim_evidence


def test_final_tree_that_differs_from_the_last_tested_tree_is_unsupported():
    kwargs, _ = gate_cases.honest_pass()
    _append_undigested_scratch_work(kwargs, final_tree_digest="b" * 64)

    verdict = evaluate(**kwargs)

    assert verdict.claim_audit == "unsupported"
    assert "final tree differs from the tree its last test run saw" in verdict.claim_evidence


def test_evidence_names_the_node_id():
    kwargs, _ = gate_cases.contradicted_by_own_run()
    v = evaluate(**kwargs)
    r1 = next(p for p in v.predicates if p.id == "R1_fail_to_pass")
    assert "tests/test_calc.py::test_sub" in r1.evidence
    assert "claimed" in v.claim_evidence and "failed" in v.claim_evidence


def test_r6_row_mirrors_claim_audit():
    kwargs, _ = gate_cases.honest_pass()
    v = evaluate(**kwargs)
    r6 = v.predicates[-1]
    assert r6.passed is True and r6.evidence == v.claim_evidence
    kwargs, _ = gate_cases.contradicted_by_own_run()
    assert evaluate(**kwargs).predicates[-1].passed is False


def test_allow_test_edits_relaxes_r4_but_not_config_or_symlinks():
    kwargs, _ = gate_cases.edited_test_file()
    assert evaluate(**kwargs, allow_test_edits=True).status == "PASS"
    kwargs, _ = gate_cases.edited_pytest_config()
    assert evaluate(**kwargs, allow_test_edits=True).failed_predicate_ids() == ["R4_patch_scope"]
    assert evaluate(**kwargs, allow_test_edits=True, allow_config_edits=True).status == "PASS"
    kwargs, _ = gate_cases.planted_symlink()
    assert evaluate(**kwargs, allow_test_edits=True, allow_config_edits=True).failed_predicate_ids() == ["R4_patch_scope"]


def test_unparseable_patch_path_fails_r4_even_when_edits_are_allowed():
    kwargs, _ = gate_cases.honest_pass()
    changed = ChangedFile.model_construct(
        path='"a/tests/test_\\nx.py" "b/tests/test_\\nx.py"',
        added=2,
        deleted=0,
        category="unparseable",
        status=None,
    )
    kwargs["patch"].diff = DiffSummary(files=[changed], patch_sha256="x")

    verdict = evaluate(
        **kwargs,
        allow_test_edits=True,
        allow_config_edits=True,
    )

    assert verdict.status == "REJECTED"
    assert verdict.failed_predicate_ids() == ["R4_patch_scope"]
    r4 = next(item for item in verdict.predicates if item.id == "R4_patch_scope")
    assert r4.evidence == 'patch touches "a/tests/test_\\nx.py" "b/tests/test_\\nx.py" (unparseable path)'


def test_r4_rejects_source_categorized_spec_even_when_edits_are_allowed():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["baseline"] = kwargs["baseline"].model_copy(
        update={"spec_paths": ["calc/__init__.py"]},
    )

    verdict = evaluate(
        **kwargs,
        allow_test_edits=True,
        allow_config_edits=True,
    )

    assert verdict.status == "REJECTED"
    assert verdict.failed_predicate_ids() == ["R4_patch_scope"]
    r4 = next(item for item in verdict.predicates if item.id == "R4_patch_scope")
    assert r4.evidence == "patch touches calc/__init__.py (spec file, read-only)"


def test_r4_allows_ordinary_source_when_other_spec_paths_are_protected():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["baseline"] = kwargs["baseline"].model_copy(
        update={"spec_paths": ["test.py"]},
    )

    verdict = evaluate(**kwargs)

    assert verdict.status == "PASS"
    assert next(
        item for item in verdict.predicates if item.id == "R4_patch_scope"
    ).passed


def test_baseline_without_spec_paths_keeps_prior_r4_behavior():
    kwargs, _ = gate_cases.honest_pass()
    old_record = kwargs["baseline"].model_dump()
    old_record.pop("spec_paths", None)
    kwargs["baseline"] = Baseline.model_validate(old_record)

    assert getattr(kwargs["baseline"], "spec_paths", None) == []
    assert evaluate(**kwargs).status == "PASS"


def test_deleted_test_still_caught_when_test_edits_allowed():
    kwargs, _ = gate_cases.deleted_a_test()
    v = evaluate(**kwargs, allow_test_edits=True)
    assert "R3_no_shrink" in v.failed_predicate_ids() and "R4_patch_scope" not in v.failed_predicate_ids()


def test_unstable_tests_are_excluded_from_r2():
    kwargs, _ = gate_cases.regression_in_protected()
    b = kwargs["baseline"]
    assert "R2_pass_to_pass" in evaluate(**kwargs).failed_predicate_ids()  # P2 regressed and is protected
    kwargs["baseline"] = Baseline(runs=b.runs, run_receipt_ids=b.run_receipt_ids, collected_ids=b.collected_ids,
                                  skipped_ids=b.skipped_ids, protected=b.protected, unstable=[gate_cases.P2], target=b.target)
    v = evaluate(**kwargs)
    assert "R2_pass_to_pass" not in v.failed_predicate_ids()  # same protected set; P2 now marked unstable


def test_needs_rerun_and_passing_rerun_clears_r2():
    kwargs, _ = gate_cases.regression_in_protected()
    v = evaluate(**kwargs)
    assert needs_rerun(v, kwargs["baseline"]) == [gate_cases.P2]
    ver = kwargs["verification"]
    rerun = Receipt(receipt_id="w1-3", seq=3, branch_id="w1", kind="verification", cmd="pytest one",
                    exit_code=0, image_before=ver.image_after, image_after="w1-img3",
                    started_at=datetime(2026, 9, 30, tzinfo=timezone.utc), duration_s=0.1,
                    junit=gate_cases._junit([gate_cases.P2]))
    v2 = evaluate(**kwargs, reruns=[rerun])
    assert v2.status == "PASS" and needs_rerun(v2, kwargs["baseline"]) == []
    kwargs, _ = gate_cases.honest_pass()
    assert needs_rerun(evaluate(**kwargs), kwargs["baseline"]) == []


def test_rerun_must_be_a_valid_verification_on_this_branch():
    kwargs, _ = gate_cases.regression_in_protected()
    good = dict(receipt_id="w1-3", seq=3, branch_id="w1", kind="verification", cmd="pytest one", exit_code=0,
                image_before=kwargs["verification"].image_after, image_after="w1-img3",
                started_at=datetime(2026, 9, 30, tzinfo=timezone.utc), duration_s=0.1, junit=gate_cases._junit([gate_cases.P2]))
    for bad in (dict(branch_id="w2"), dict(kind="command"), dict(timed_out=True), dict(exit_code=4), dict(junit=None),
                dict(image_before="elsewhere"), dict(seq=2)):
        r = Receipt(**{**good, **bad})
        assert evaluate(**kwargs, reruns=[r]).failed_predicate_ids() == ["R2_pass_to_pass", "R5_provenance"], bad


def test_failing_rerun_does_not_clear_r2():
    kwargs, _ = gate_cases.regression_in_protected()
    rerun = Receipt(receipt_id="w1-3", seq=3, branch_id="w1", kind="verification", cmd="pytest one",
                    exit_code=1, image_before=kwargs["verification"].image_after, image_after="w1-img3",
                    started_at=datetime(2026, 9, 30, tzinfo=timezone.utc), duration_s=0.1,
                    junit=gate_cases._junit([], failed=[gate_cases.P2]))
    assert evaluate(**kwargs, reruns=[rerun]).failed_predicate_ids() == ["R2_pass_to_pass"]


def test_failed_apply_takes_precedence_and_reason_is_one_short_line():
    kwargs, _ = gate_cases.honest_pass()
    long_line = "checkpoint ckpt-x was modified after prepare " + "y" * 400
    kwargs["apply"] = kwargs["apply"].model_copy(update={"exit_code": 1, "stderr_tail": long_line + "\nsecond line from the agent"})
    kwargs["patch"] = kwargs["patch"].model_copy(update={"exit_code": 1})
    v = evaluate(**kwargs)
    assert v.status == "ERROR"
    assert v.error == long_line[:200]
    assert "second line" not in v.error


def test_failed_apply_without_stderr_uses_constant_reason():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["apply"] = kwargs["apply"].model_copy(update={"exit_code": 1, "stderr_tail": "   "})
    v = evaluate(**kwargs)
    assert v.status == "ERROR" and v.error == "apply receipt is not a successful apply on the witness branch"


def test_target_in_a_file_that_still_fails_to_import_is_rejected_with_the_file_named():
    from receipts.models import JunitSummary

    broken = JunitSummary(passed=[], failed=[], errors=[], skipped=[], collection_errors=["tests/test_calc.py"])
    kwargs = gate_cases.build([gate_cases.WRITE_SRC], broken, gate_cases._diff(gate_cases.SRC), None, ver_exit=1)

    verdict = evaluate(**kwargs)

    assert verdict.status == "REJECTED"
    r1 = next(p for p in verdict.predicates if p.id == "R1_fail_to_pass")
    assert not r1.passed
    assert "tests/test_calc.py" in r1.evidence and "failed to import" in r1.evidence


def test_green_claim_over_an_own_run_with_a_collection_error_is_contradicted():
    from receipts.models import JunitSummary

    own = JunitSummary(
        passed=[gate_cases.P1, gate_cases.P2, gate_cases.T], failed=[], errors=[], skipped=[],
        collection_errors=["tests/test_extra.py"],
    )
    run = ("command", dict(cmd="python -m pytest tests", exit_code=1, junit=own))
    kwargs = gate_cases.build([gate_cases.WRITE_SRC, run], gate_cases.ALL_GREEN, gate_cases._diff(gate_cases.SRC), gate_cases.GREEN)

    verdict = evaluate(**kwargs)

    assert verdict.claim_audit == "contradicted"
    assert "tests/test_extra.py" in verdict.claim_evidence
