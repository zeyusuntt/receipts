import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from receipts.models import Baseline, ChangedFile, DiffSummary, JunitSummary, PatchScope, Receipt, Verdict
from receipts.verify.gate import evaluate, needs_rerun
from tests.fixtures import gate_cases


QISKIT_FIXTURES = Path(__file__).parent / "fixtures" / "qiskit_ibm_runtime_452"


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
    expected_kind = (
        "infrastructure"
        if kwargs["verification"] is not None
        and not kwargs["verification"].timed_out
        and kwargs["verification"].exit_code in (2, 3, 4)
        else "attempt"
    )
    assert v.error_kind == expected_kind
    # The audit still reflects what the worker said, even when verification broke.
    assert v.claim_audit == ("no_claim" if kwargs["claims"] is None else "honest")


def _load_confirmation(*, exit_code=4, patch_sha256=gate_cases.FILTERED_SHA):
    chain = gate_cases.Chain(branch="c1")
    applied = chain.add(
        "apply",
        exit_code=0,
        patch_sha256=patch_sha256,
    )
    verified = chain.add(
        "verification",
        cmd="python -m pytest tests",
        exit_code=exit_code,
        junit=None,
    )
    return applied, verified


def test_confirmed_pytest_exit_4_is_rejected_with_load_evidence():
    kwargs, _ = gate_cases.honest_pass()
    output = "discarded prefix\n" + "x" * 1_490 + "\nSyntaxError: broken source\n"
    kwargs["verification"] = kwargs["verification"].model_copy(
        update={"exit_code": 4, "junit": None, "stdout_tail": output},
    )
    confirmation_apply, confirmation = _load_confirmation()

    verdict = evaluate(
        **kwargs,
        load_confirmation_apply=confirmation_apply,
        load_confirmation=confirmation,
    )

    assert verdict.status == "REJECTED"
    assert verdict.error_kind is None
    assert verdict.failed_predicate_ids() == [
        "R1_fail_to_pass",
        "R2_pass_to_pass",
        "R3_no_shrink",
    ]
    predicates = {predicate.id: predicate for predicate in verdict.predicates}
    r1 = predicates["R1_fail_to_pass"]
    expected_tail = output.strip()[-1_500:]
    assert r1.evidence == (
        "the suite could not load with this patch (pytest exit 4): "
        + expected_tail
    )
    assert predicates["R2_pass_to_pass"].evidence == (
        "not evaluable: the suite did not load"
    )
    assert predicates["R3_no_shrink"].evidence == (
        "not evaluable: the suite did not load"
    )
    assert predicates["R4_patch_scope"].passed is True
    assert predicates["R5_provenance"].passed is True


def test_unconfirmed_pytest_exit_4_is_an_infrastructure_error():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["verification"] = kwargs["verification"].model_copy(
        update={"exit_code": 4, "junit": None},
    )

    verdict = evaluate(**kwargs)

    assert verdict.status == "ERROR"
    assert verdict.error_kind == "infrastructure"
    assert verdict.error == (
        "infrastructure: the suite failed to load (pytest exit 4) and a "
        "second clean witness did not reproduce it"
    )


def test_confirmation_that_exits_1_does_not_confirm_load_failure():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["verification"] = kwargs["verification"].model_copy(
        update={"exit_code": 4, "junit": None},
    )
    confirmation_apply, confirmation = _load_confirmation(exit_code=1)

    verdict = evaluate(
        **kwargs,
        load_confirmation_apply=confirmation_apply,
        load_confirmation=confirmation,
    )

    assert verdict.status == "ERROR"
    assert verdict.error_kind == "infrastructure"


def test_confirmation_with_a_different_apply_digest_does_not_confirm_load_failure():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["verification"] = kwargs["verification"].model_copy(
        update={"exit_code": 4, "junit": None},
    )
    confirmation_apply, confirmation = _load_confirmation(
        patch_sha256="different",
    )

    verdict = evaluate(
        **kwargs,
        load_confirmation_apply=confirmation_apply,
        load_confirmation=confirmation,
    )

    assert verdict.status == "ERROR"
    assert verdict.error_kind == "infrastructure"


def test_first_witness_receipts_cannot_confirm_their_own_load_failure():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["verification"] = kwargs["verification"].model_copy(
        update={"exit_code": 4, "junit": None},
    )

    verdict = evaluate(
        **kwargs,
        load_confirmation_apply=kwargs["apply"],
        load_confirmation=kwargs["verification"],
    )

    assert verdict.status == "ERROR"
    assert verdict.error_kind == "infrastructure"


def test_disconnected_receipts_cannot_confirm_load_failure():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["verification"] = kwargs["verification"].model_copy(
        update={"exit_code": 4, "junit": None},
    )
    confirmation_apply, confirmation = _load_confirmation()
    confirmation = confirmation.model_copy(
        update={
            "branch_id": "unrelated",
            "image_before": "not-the-apply-output",
            "seq": confirmation_apply.seq,
        },
    )

    verdict = evaluate(
        **kwargs,
        load_confirmation_apply=confirmation_apply,
        load_confirmation=confirmation,
    )

    assert verdict.status == "ERROR"
    assert verdict.error_kind == "infrastructure"


def test_timeout_and_exit_137_are_attempt_errors():
    timeout_kwargs, _ = gate_cases.honest_pass()
    timeout_kwargs["verification"] = timeout_kwargs["verification"].model_copy(
        update={"exit_code": 4, "timed_out": True, "junit": None},
    )
    killed_kwargs, _ = gate_cases.honest_pass()
    killed_kwargs["verification"] = killed_kwargs["verification"].model_copy(
        update={"exit_code": 137, "junit": None},
    )

    timed_out = evaluate(**timeout_kwargs)
    killed = evaluate(**killed_kwargs)

    assert timed_out.status == "ERROR" and timed_out.error_kind == "attempt"
    assert killed.status == "ERROR" and killed.error_kind == "attempt"


def test_old_verdict_json_without_error_kind_loads():
    kwargs, _ = gate_cases.honest_pass()
    payload = evaluate(**kwargs).model_dump(mode="json")
    payload.pop("error_kind")

    loaded = Verdict.model_validate(payload)

    assert loaded.error_kind is None


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


def test_r2_rejects_real_qiskit_subtest_regression():
    baseline_fields = json.loads(
        (QISKIT_FIXTURES / "baseline.json").read_text(encoding="utf-8"),
    )
    verification_junit = JunitSummary.model_validate_json(
        (QISKIT_FIXTURES / "verification_junit.json").read_text(encoding="utf-8"),
    )
    kwargs, _ = gate_cases.honest_pass()
    kwargs["baseline"] = kwargs["baseline"].model_copy(update=baseline_fields)
    kwargs["verification"] = kwargs["verification"].model_copy(
        update={"exit_code": 1, "junit": verification_junit},
    )

    verdict = evaluate(**kwargs)

    r2 = next(item for item in verdict.predicates if item.id == "R2_pass_to_pass")
    affected = (
        "test/unit/test_account.py::TestEnableAccount::"
        "test_enable_account_by_env_pref"
    )
    assert verdict.failed_predicate_ids() == ["R2_pass_to_pass"]
    assert not r2.passed
    assert affected in r2.evidence


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


def _replace_patch_files(kwargs, *files):
    kwargs["patch"].diff = DiffSummary(
        files=list(files),
        patch_sha256="x",
    )


def _scope(*, protected_names, c0_top_level):
    return PatchScope(
        protected_names=list(protected_names),
        c0_top_level=list(c0_top_level),
    )


def test_r4_rejects_launch_3_root_package_copy_with_shadow_evidence():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["baseline"] = kwargs["baseline"].model_copy(
        update={
            "scope": _scope(
                protected_names=["scikit_build_core"],
                c0_top_level=["src/scikit_build_core"],
            ),
        },
    )
    _replace_patch_files(
        kwargs,
        ChangedFile(
            path="scikit_build_core/build/_scripts.py",
            added=1,
            deleted=0,
            category="source",
            status="added",
        ),
        ChangedFile(
            path="src/scikit_build_core/build/_scripts.py",
            added=1,
            deleted=1,
            category="source",
            status="modified",
        ),
    )

    verdict = evaluate(**kwargs)

    assert verdict.status == "REJECTED"
    assert verdict.failed_predicate_ids() == ["R4_patch_scope"]
    r4 = next(item for item in verdict.predicates if item.id == "R4_patch_scope")
    assert r4.evidence == (
        "patch touches scikit_build_core/build/_scripts.py "
        "(shadows scikit_build_core, which is protected)"
    )


def test_r4_rejects_launch_2_root_package_copy_with_shadow_evidence():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["baseline"] = kwargs["baseline"].model_copy(
        update={
            "scope": _scope(
                protected_names=["scikit_build_core"],
                c0_top_level=["src/scikit_build_core"],
            ),
        },
    )
    _replace_patch_files(
        kwargs,
        ChangedFile(
            path="scikit_build_core/__init__.py",
            added=1,
            deleted=0,
            category="source",
            status="added",
        ),
    )

    verdict = evaluate(**kwargs)

    assert verdict.status == "REJECTED"
    r4 = next(item for item in verdict.predicates if item.id == "R4_patch_scope")
    assert r4.evidence == (
        "patch touches scikit_build_core/__init__.py "
        "(shadows scikit_build_core, which is protected)"
    )


def test_r4_allows_added_file_inside_existing_flat_package():
    kwargs, _ = gate_cases.honest_pass()
    kwargs["baseline"] = kwargs["baseline"].model_copy(
        update={
            "scope": _scope(
                protected_names=["pkg"],
                c0_top_level=["pkg"],
            ),
        },
    )
    _replace_patch_files(
        kwargs,
        ChangedFile(
            path="pkg/new.py",
            added=1,
            deleted=0,
            category="source",
            status="added",
        ),
    )

    assert evaluate(**kwargs).status == "PASS"


def test_r4_rejects_reserved_startup_hook_before_added_test_exemption():
    kwargs, _ = gate_cases.honest_pass()
    _replace_patch_files(
        kwargs,
        ChangedFile(
            path="src/sitecustomize.py",
            added=1,
            deleted=0,
            category="reserved",
            status="added",
        ),
    )

    verdict = evaluate(**kwargs)

    assert verdict.status == "REJECTED"
    assert verdict.failed_predicate_ids() == ["R4_patch_scope"]
    r4 = next(item for item in verdict.predicates if item.id == "R4_patch_scope")
    assert r4.evidence == "patch touches src/sitecustomize.py (reserved)"


def test_baseline_without_scope_keeps_prior_r4_behavior():
    kwargs, _ = gate_cases.honest_pass()
    old_record = kwargs["baseline"].model_dump()
    old_record.pop("scope", None)
    kwargs["baseline"] = Baseline.model_validate(old_record)
    _replace_patch_files(
        kwargs,
        ChangedFile(
            path="scikit_build_core/build/_scripts.py",
            added=1,
            deleted=0,
            category="source",
            status="added",
        ),
    )

    assert kwargs["baseline"].scope is None
    assert evaluate(**kwargs).status == "PASS"


def _replace_patch_file(kwargs, *, path="test_scratch.py", status):
    kwargs["patch"].diff = DiffSummary(
        files=[ChangedFile(
            path=path,
            added=1,
            deleted=0,
            category="test",
            status=status,
        )],
        patch_sha256="x",
    )


def test_r4_allows_added_test_file():
    kwargs, _ = gate_cases.honest_pass()
    _replace_patch_file(kwargs, status="added")

    verdict = evaluate(**kwargs)

    assert verdict.status == "PASS"
    assert next(
        item for item in verdict.predicates if item.id == "R4_patch_scope"
    ).passed


@pytest.mark.parametrize("status", ["modified", "deleted", None])
def test_r4_rejects_test_file_that_is_not_known_to_be_added(status):
    kwargs, _ = gate_cases.honest_pass()
    _replace_patch_file(kwargs, status=status)

    verdict = evaluate(**kwargs)

    assert verdict.status == "REJECTED"
    assert verdict.failed_predicate_ids() == ["R4_patch_scope"]


def test_r4_rejects_added_test_file_when_it_is_a_spec_path():
    kwargs, _ = gate_cases.honest_pass()
    _replace_patch_file(kwargs, path="tests/test_spec.py", status="added")
    kwargs["baseline"] = kwargs["baseline"].model_copy(
        update={"spec_paths": ["tests/test_spec.py"]},
    )

    verdict = evaluate(**kwargs)

    assert verdict.status == "REJECTED"
    assert verdict.failed_predicate_ids() == ["R4_patch_scope"]
    r4 = next(item for item in verdict.predicates if item.id == "R4_patch_scope")
    assert r4.evidence == "patch touches tests/test_spec.py (spec file, read-only)"


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


def test_r1_requires_every_full_id_mapped_at_baseline_to_pass():
    truncated = "tests/test_900_rules.py::test_sim910[d.get(key,"
    full_first = (
        "tests/test_900_rules.py::test_sim910[d.get(key, None)-"
        "SIM910 Use 'd.get(key)' instead of 'd.get(key, None)']"
    )
    full_second = full_first.replace("None", "missing")
    kwargs, _ = gate_cases.honest_pass()
    baseline = kwargs["baseline"]
    kwargs["baseline"] = baseline.model_copy(
        update={
            "collected_ids": [gate_cases.P1, gate_cases.P2, full_first, full_second],
            "target": [full_first, full_second],
            "target_map": {truncated: [full_first, full_second]},
        },
    )
    kwargs["verification"] = kwargs["verification"].model_copy(
        update={
            "junit": gate_cases._junit(
                [gate_cases.P1, gate_cases.P2, full_first],
                failed=[full_second],
            ),
            "exit_code": 1,
        },
    )

    verdict = evaluate(**kwargs)

    r1 = next(predicate for predicate in verdict.predicates if predicate.id == "R1_fail_to_pass")
    assert r1.passed is False
    assert full_second in r1.evidence
    assert full_first not in r1.evidence


def test_r1_maps_an_unmapped_legacy_target_against_witness_ids():
    truncated = "tests/test_900_rules.py::test_sim910[d.get(key,"
    full = (
        "tests/test_900_rules.py::test_sim910[d.get(key, None)-"
        "SIM910 Use 'd.get(key)' instead of 'd.get(key, None)']"
    )
    kwargs, _ = gate_cases.honest_pass()
    baseline = kwargs["baseline"]
    kwargs["baseline"] = baseline.model_copy(
        update={
            "collected_ids": [gate_cases.P1, gate_cases.P2],
            "target": [truncated],
            "target_map": {},
        },
    )
    kwargs["verification"] = kwargs["verification"].model_copy(
        update={
            "junit": gate_cases._junit([gate_cases.P1, gate_cases.P2, full]),
            "exit_code": 0,
        },
    )

    verdict = evaluate(**kwargs)

    r1 = next(predicate for predicate in verdict.predicates if predicate.id == "R1_fail_to_pass")
    assert r1.passed is True
    assert full in r1.evidence


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
