from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from receipts.pilot.runner import (
    AttemptRecord,
    FinalRecord,
    InstanceRecord,
    PilotCost,
)
from receipts.pilot.grade import OfficialRecord


def _report_module():
    try:
        from receipts.pilot import report
    except ModuleNotFoundError:
        pytest.fail("Task P4 report module is missing")
    return report


def _attempt(
    *,
    claimed_done: bool = True,
    naive_green: bool = False,
    gate_status: str = "REJECTED",
    failed: Sequence[str] = (),
    claim_audit: str = "honest",
    official_resolved: bool | None = False,
    agreement: str | None = "agree_fail",
    gate_error: str | None = None,
    filtered_sha256: str | None = None,
    witness_apply_sha256: str | None = None,
    applied_sha256: str | None = None,
    read_sha256: str | None = None,
) -> AttemptRecord:
    return AttemptRecord(
        end="finished",
        claimed_done=claimed_done,
        claims=None,
        naive_green=naive_green,
        gate_status=gate_status,
        failed_predicate_ids=list(failed),
        claim_audit=claim_audit,
        official_resolved=official_resolved,
        agreement=agreement,
        filtered_patch_sha256="a" * 64,
        filtered_sha256=filtered_sha256,
        witness_apply_sha256=witness_apply_sha256,
        gate_error=gate_error,
        official=(
            OfficialRecord.model_construct(applied_sha256=applied_sha256, read_sha256=read_sha256)
            if applied_sha256 is not None or read_sha256 is not None
            else None
        ),
    )


def _record(
    instance_id: str,
    attempts: Sequence[AttemptRecord],
    *,
    verified_fix: bool = False,
    status: str = "ran",
    reason: str | None = None,
    tokens: int = 10,
    model_dollars: float | None = 1.0,
    sandbox_lifetime_seconds: float = 20.0,
    sandbox_dollars_estimate: float = 0.0,
    wall_time_s: float = 30.0,
    run_dir: str | None = None,
) -> InstanceRecord:
    final = None
    if attempts:
        last = attempts[-1]
        final = FinalRecord(
            gate_status=last.gate_status,
            verified_fix=verified_fix,
            official_resolved=last.official_resolved,
        )
    return InstanceRecord(
        instance_id=instance_id,
        status=status,
        reason=reason,
        run_dir=run_dir or f"pilot/{instance_id}/runs/run-1",
        attempts=list(attempts),
        final=final,
        cost=PilotCost(
            tokens=tokens,
            model_dollars=model_dollars,
            sandbox_lifetime_seconds=sandbox_lifetime_seconds,
            sandbox_dollars_estimate=sandbox_dollars_estimate,
        ),
        wall_time_s=wall_time_s,
    )


def _claimed_records(false_dones: int, claimed_dones: int) -> list[InstanceRecord]:
    return [
        _record(
            f"task-{index:03d}",
            [
                _attempt(
                    gate_status="REJECTED" if index < false_dones else "PASS",
                    official_resolved=index >= false_dones,
                    agreement="agree_fail" if index < false_dones else "agree_pass",
                ),
            ],
            verified_fix=index >= false_dones,
        )
        for index in range(claimed_dones)
    ]


@pytest.mark.parametrize(
    ("false_dones", "claimed_dones", "lower", "upper"),
    [
        (0, 10, 0.0, 0.2775328),
        (5, 20, 0.1118617, 0.4687009),
        (20, 20, 0.8388748, 1.0),
    ],
)
def test_false_done_rate_uses_wilson_95_percent_interval(
    false_dones: int,
    claimed_dones: int,
    lower: float,
    upper: float,
):
    report = _report_module().build_report(
        _claimed_records(false_dones, claimed_dones),
    )

    rate = report.configuration_a.false_done_rate
    assert rate.numerator == false_dones
    assert rate.denominator == claimed_dones
    assert rate.value == pytest.approx(false_dones / claimed_dones)
    assert rate.lower_95 == pytest.approx(lower, abs=1e-7)
    assert rate.upper_95 == pytest.approx(upper, abs=1e-7)


def test_h1_is_chosen_at_five_false_dones_and_ten_percent_but_not_four():
    report_module = _report_module()

    at_threshold = report_module.build_report(_claimed_records(5, 50))
    below_count = report_module.build_report(_claimed_records(4, 40))

    assert at_threshold.headline == (
        "10 percent of an unguarded agent's 'done' was false; "
        "Receipts shipped zero."
    )
    assert below_count.headline == (
        "What a verified fix costs: dollars, minutes and zero shipped failures "
        "across 40 SWE-rebench tasks."
    )


def test_h3_is_appended_only_below_fifteen_percent_verified():
    report_module = _report_module()
    below = _claimed_records(0, 20)
    at_threshold = _claimed_records(0, 20)
    for record in below + at_threshold:
        record.final.verified_fix = False
    for record in below[:2]:
        record.final.verified_fix = True
    for record in at_threshold[:3]:
        record.final.verified_fix = True

    below_report = report_module.build_report(below)
    threshold_report = report_module.build_report(at_threshold)

    assert below_report.secondary_headline == (
        "Knowing when not to ship: every unverified patch was refused, "
        "with the evidence published."
    )
    assert threshold_report.secondary_headline is None


def test_report_computes_all_sections_from_records():
    report_module = _report_module()
    false_on_appeal = _record(
        "project__false-on-appeal",
        [
            _attempt(
                naive_green=True,
                failed=["R1_fail_to_pass", "R4_patch_scope"],
                claim_audit="unsupported",
            ),
            _attempt(
                gate_status="PASS",
                official_resolved=True,
                agreement="agree_pass",
            ),
        ],
        verified_fix=True,
        tokens=100,
        model_dollars=2.0,
        sandbox_lifetime_seconds=40.0,
        wall_time_s=60.0,
    )
    shipped_false_done = _record(
        "project__shipped-false",
        [
            _attempt(
                naive_green=True,
                gate_status="PASS",
                official_resolved=False,
                agreement="gate_looser",
            ),
        ],
        tokens=20,
        model_dollars=1.0,
        sandbox_lifetime_seconds=10.0,
        wall_time_s=20.0,
    )
    verified_first = _record(
        "project__verified-first",
        [
            _attempt(
                gate_status="PASS",
                official_resolved=True,
                agreement="agree_pass",
            ),
        ],
        verified_fix=True,
        tokens=40,
        model_dollars=1.0,
        sandbox_lifetime_seconds=20.0,
        wall_time_s=40.0,
    )
    gate_stricter = _record(
        "project__gate-stricter",
        [
            _attempt(
                claimed_done=False,
                gate_status="REJECTED",
                failed=["R3_no_shrink"],
                official_resolved=True,
                agreement="gate_stricter",
            ),
        ],
        tokens=20,
        model_dollars=0.0,
        sandbox_lifetime_seconds=10.0,
        wall_time_s=20.0,
    )
    gate_error = _record(
        "project__gate-error",
        [
            _attempt(
                claimed_done=False,
                gate_status="ERROR",
                failed=["R5_provenance"],
                official_resolved=False,
                agreement="gate_error",
            ),
        ],
        tokens=20,
        model_dollars=0.0,
        sandbox_lifetime_seconds=10.0,
        wall_time_s=20.0,
    )
    excluded = _record(
        "project__excluded",
        [],
        status="excluded",
        reason="target already passes",
        tokens=0,
        model_dollars=None,
        sandbox_lifetime_seconds=0,
        wall_time_s=1.0,
    )
    infra_error = _record(
        "project__infra",
        [],
        status="infra_error",
        reason="RuntimeError: sandbox failed",
        tokens=0,
        model_dollars=None,
        sandbox_lifetime_seconds=0,
        wall_time_s=2.0,
    )
    records = [
        shipped_false_done,
        excluded,
        gate_error,
        false_on_appeal,
        infra_error,
        verified_first,
        gate_stricter,
    ]

    report = report_module.build_report(records)

    assert report.ran_tasks == 5
    assert report.configuration_a.claimed_dones == 3
    assert report.configuration_a.false_dones == 2
    assert report.configuration_a.naive_green_false_dones == 2
    assert report.configuration_a.breakdown == {
        "spec_still_failing": 1,
        "regression": 0,
        "tests_removed_or_newly_skipped": 0,
        "test_or_config_edited": 1,
        "tests_never_run_on_final_state": 1,
    }
    assert report.configuration_b.verified_fixes == 2
    assert report.configuration_b.first_verdict == 1
    assert report.configuration_b.appeal == 1
    assert report.configuration_b.shipped_false_dones == 1
    assert report.configuration_b.cost_per_verified_fix.tokens == 100
    assert report.configuration_b.cost_per_verified_fix.model_dollars == 2.0
    assert report.configuration_b.cost_per_verified_fix.sandbox_dollars_estimate == 0
    assert report.configuration_b.cost_per_verified_fix.total_dollars_estimate == 2.0
    assert (
        report.configuration_b.cost_per_verified_fix.sandbox_lifetime_seconds
        == 45.0
    )
    assert report.configuration_b.cost_per_verified_fix.wall_time_s == 80.0
    assert report.agreement.matrix == {
        "PASS": {"resolved": 2, "not_resolved": 1, "unavailable": 0},
        "REJECTED": {"resolved": 1, "not_resolved": 1, "unavailable": 0},
        "ERROR": {"resolved": 0, "not_resolved": 1, "unavailable": 0},
    }
    assert [item.agreement for item in report.agreement.disagreements] == [
        "gate_error",
        "gate_stricter",
        "gate_looser",
    ]
    assert report.exclusions[0].instance_id == "project__excluded"
    assert report.infrastructure_errors[0].reason == "RuntimeError: sandbox failed"
    assert [row.instance_id for row in report.instances] == sorted(
        record.instance_id for record in records
    )

    markdown = report_module.render(report)
    assert markdown.splitlines()[0] == "Receipts shipped 1 false done."
    assert "A false done can appear in more than one breakdown row." in markdown
    assert "project__gate-stricter" in markdown
    assert "R3_no_shrink" in markdown
    assert "project__excluded" in markdown
    assert "project__infra" in markdown
    assert "pilot/project__verified-first/runs/run-1" in markdown


def test_same_records_produce_byte_identical_reports():
    report_module = _report_module()
    records = _claimed_records(2, 10)

    first = report_module.build_report(records)
    second = report_module.build_report(list(reversed(records)))

    assert report_module.render(first).encode() == report_module.render(second).encode()
    assert first.model_dump_json() == second.model_dump_json()


def test_report_lists_instances_with_truncated_target_ids_and_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    report_module = _report_module()
    monkeypatch.setattr(report_module, "_REPOSITORY_ROOT", tmp_path)
    dataset_key = "tests/test_900_rules.py::test_sim910[d.get(key,"
    dataset_quoted = "tests/test_900_rules.py::test_sim910[d.get('key',"
    full_key = (
        "tests/test_900_rules.py::test_sim910[d.get(key, None)-"
        "SIM910 Use 'd.get(key)' instead of 'd.get(key, None)']"
    )
    full_other = full_key.replace("None", "missing")
    full_quoted = (
        "tests/test_900_rules.py::test_sim910[d.get('key', None)-"
        'SIM910 Use \'d.get("key")\' instead of \'d.get(\'key\', None)\']'
    )

    mapped_dir = tmp_path / "mapped"
    mapped_dir.mkdir()
    (mapped_dir / "baseline.json").write_text(
        json.dumps(
            {
                "target_map": {
                    dataset_key: [full_key, full_other],
                    dataset_quoted: [full_quoted],
                },
            },
        ),
        encoding="utf-8",
    )
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "baseline.json").write_text(
        json.dumps(
            {
                "target_map": {
                    "tests/test_x.py::test_x": ["tests/test_x.py::test_x"],
                },
            },
        ),
        encoding="utf-8",
    )
    records = [
        _record(
            "martinthoma__flake8-simplify-173",
            [_attempt()],
            run_dir="mapped",
        ),
        _record("identity", [_attempt()], run_dir="identity"),
        _record("legacy-without-target-map", [_attempt()], run_dir="legacy"),
    ]

    markdown = report_module.render(report_module.build_report(records))

    assert (
        "Truncated test ids: martinthoma__flake8-simplify-173 "
        "(2 dataset ids, 3 full ids)."
    ) in markdown
    truncated_line = next(
        line for line in markdown.splitlines() if line.startswith("Truncated test ids:")
    )
    assert "identity" not in truncated_line
    assert "legacy-without-target-map" not in truncated_line


def test_harness_keeps_good_rows_counts_bad_ones_and_maps_old_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    report_module = _report_module()
    monkeypatch.setattr(report_module, "_REPOSITORY_ROOT", tmp_path)

    def result(call_id, name, ran_as, result_class, **extra):
        return {
            "id": call_id,
            "name": name,
            "ran_as": ran_as,
            "executed": ran_as is not None,
            "class": result_class,
            "result_bytes": 10,
            **extra,
        }

    log = tmp_path / "pilot" / "run-x" / "task" / "runs" / "r1" / "agent" / "worker.jsonl"
    log.parent.mkdir(parents=True)
    rows = [
        {"results": [result("e1", "edit_file", "edit_file", "ok", future_field=1)]},
        {"results": [result("e2", "edit_file", None, "bad_args")]},
        {"results": [result("e3", "str_replace_editor", "edit_file", "edit_invalid_utf8")]},
        {"results": [result("e4", "edit_file", "edit_file", "edit_no_match")]},
    ]
    log.write_text(
        "".join(json.dumps(row) + "\n" for row in rows) + '{"results": [{"id": "trunc',
    )
    old_absolute = "/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-x/task/runs/r1"

    report = report_module.build_report([_record("old-path", [_attempt()], run_dir=old_absolute)])

    assert report.harness.unreadable_logs == 0
    assert report.harness.unreadable_rows == 1
    assert report.harness.total_tool_calls == 4
    assert report.harness.edit_failure_rate.numerator == 3
    assert report.harness.edit_failure_rate.denominator == 4
    markdown = report_module.render(report)
    assert "edit calls that did not apply" in markdown


def test_harness_section_counts_results_aliases_edit_failures_and_legacy_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    report_module = _report_module()
    monkeypatch.setattr(report_module, "_REPOSITORY_ROOT", tmp_path)

    absolute_run = tmp_path / "absolute-run"
    relative_run = tmp_path / "relative-run"
    invalid_run = tmp_path / "invalid-run"
    absolute_log = absolute_run / "agent" / "worker.jsonl"
    relative_log = relative_run / "agent" / "worker.jsonl"
    invalid_log = invalid_run / "agent" / "worker.jsonl"
    absolute_log.parent.mkdir(parents=True)
    relative_log.parent.mkdir(parents=True)
    invalid_log.parent.mkdir(parents=True)
    absolute_rows = [
        {
            "context_guard": {
                "replaced_messages": 2,
                "estimated_tokens_before": 170_000,
                "estimated_tokens_after": 150_000,
            },
            "results": [
                {
                    "id": "edit-1",
                    "name": "edit_file",
                    "ran_as": "edit_file",
                    "executed": True,
                    "class": "edit_no_match",
                    "result_bytes": 32,
                },
                {
                    "id": "command-1",
                    "name": "execute",
                    "ran_as": "run_command",
                    "executed": True,
                    "class": "nonzero_exit",
                    "result_bytes": 38,
                },
                {
                    "id": "read-1",
                    "name": "read_file",
                    "ran_as": "read_file",
                    "executed": True,
                    "class": "ok",
                    "result_bytes": 100,
                },
            ],
        },
        {"tool_calls": [{"id": "legacy"}]},
    ]
    relative_rows = [
        {
            "context_guard": {
                "replaced_messages": 3,
                "estimated_tokens_before": 180_000,
                "estimated_tokens_after": 140_000,
            },
            "results": [
                {
                    "id": "edit-2",
                    "name": "str_replace_editor",
                    "ran_as": "edit_file",
                    "executed": True,
                    "class": "edit_multiple_matches",
                    "result_bytes": 55,
                },
                {
                    "id": "edit-3",
                    "name": "edit_file",
                    "ran_as": "edit_file",
                    "executed": True,
                    "class": "ok",
                    "result_bytes": 2,
                },
                {
                    "id": "think-1",
                    "name": "think",
                    "ran_as": None,
                    "executed": False,
                    "class": "noted",
                    "result_bytes": 5,
                },
            ],
        },
    ]
    absolute_log.write_text(
        "".join(json.dumps(row) + "\n" for row in absolute_rows),
    )
    relative_log.write_text(
        "".join(json.dumps(row) + "\n" for row in relative_rows),
    )
    invalid_log.write_text(json.dumps({"results": [{"class": "invented"}]}) + "\n")
    records = [
        _record("absolute", [_attempt()], run_dir=str(absolute_run)),
        _record("relative", [_attempt()], run_dir="relative-run"),
        _record("invalid", [_attempt()], run_dir="invalid-run"),
        _record("missing", [_attempt()], run_dir="missing-run"),
    ]

    report = report_module.build_report(records)

    assert report.harness.total_tool_calls == 6
    assert report.harness.classes["ok"] == 2
    assert report.harness.classes["edit_no_match"] == 1
    assert report.harness.classes["edit_multiple_matches"] == 1
    assert report.harness.classes["nonzero_exit"] == 1
    assert report.harness.classes["noted"] == 1
    assert report.harness.aliases == {"execute": 1, "str_replace_editor": 1}
    assert report.harness.edit_failure_rate.numerator == 2
    assert report.harness.edit_failure_rate.denominator == 3
    assert report.harness.context_guard_turns == 2
    assert report.harness.context_guard_replaced_messages == 5
    assert report.harness.not_recorded == 1
    assert report.harness.unreadable_logs == 1
    assert report.harness.unreadable_rows == 1

    markdown = report_module.render(report)
    harness = markdown.split("## Harness", 1)[1].split("## Shipped bytes", 1)[0]
    assert "Total tool calls: 6." in harness
    assert "edit_no_match | 1" in harness
    assert "edit_multiple_matches | 1" in harness
    assert "execute | 1" in harness
    assert "str_replace_editor | 1" in harness
    assert "Edit-failure rate (edit calls that did not apply, over all edit calls): 2 of 3" in harness
    assert "Context guard: 2 turns; 5 messages replaced." in harness
    assert "1 turn not recorded" in harness
    assert "1 worker log unreadable or missing; 1 unreadable row skipped" in harness


def test_report_lists_shipped_byte_digest_agreement_mismatches_and_old_records():
    digest = "a" * 64
    records = [
        _record(
            "project__agree",
            [
                _attempt(
                    filtered_sha256=digest,
                    witness_apply_sha256=digest,
                    applied_sha256=digest,
                ),
            ],
        ),
        _record(
            "project__mismatch",
            [
                _attempt(
                    filtered_sha256=digest,
                    witness_apply_sha256="b" * 64,
                    applied_sha256=digest,
                ),
            ],
        ),
        _record("project__legacy", [_attempt()]),
    ]

    markdown = _report_module().render(_report_module().build_report(records))

    assert "Shipped bytes: digests agree on 1 of 2 attempts." in markdown
    assert "1 attempt not recorded (records before this check)." in markdown
    shipped_bytes = markdown.split("## Shipped bytes", 1)[1].split(
        "## Gate and official-grader agreement",
        1,
    )[0]
    assert "project__mismatch" in shipped_bytes
    assert "| 1 |" in shipped_bytes
    assert "project__agree" not in shipped_bytes
    assert "project__legacy" not in shipped_bytes


def test_report_counts_a_patch_changed_before_grading_as_a_mismatch():
    digest = "a" * 64
    records = [
        _record(
            "project__changed_after_gate",
            [
                _attempt(
                    filtered_sha256=digest,
                    witness_apply_sha256=digest,
                    read_sha256="c" * 64,
                ),
            ],
        ),
    ]

    report = _report_module().build_report(records)

    assert report.shipped_bytes.recorded == 1
    assert report.shipped_bytes.not_recorded == 0
    assert [m.instance_id for m in report.shipped_bytes.mismatches] == ["project__changed_after_gate"]


def test_infrastructure_record_gate_error_is_listed_with_error_text():
    report_module = _report_module()
    attempt = _attempt(
        claimed_done=False,
        gate_status="ERROR",
        official_resolved=None,
        agreement=None,
        gate_error="witness verification exited 3",
    )
    record = _record(
        "project__infra-gate-error",
        [attempt],
        status="infra_error",
        reason="official grading failed after gate error",
        tokens=0,
        model_dollars=None,
        sandbox_lifetime_seconds=0,
    )

    markdown = report_module.render(report_module.build_report([record]))

    section = markdown.split("### Disagreements and gate errors", 1)[1].split(
        "## Exclusions",
        1,
    )[0]
    assert "project__infra-gate-error" in section
    assert "witness verification exited 3" in section


def test_report_lists_every_prior_infrastructure_error_for_retried_instance():
    report_module = _report_module()
    record = _record(
        "project__retried",
        [_attempt(gate_status="PASS", official_resolved=True, agreement="agree_pass")],
        verified_fix=True,
    )
    record = InstanceRecord.model_validate(
        {
            **record.model_dump(mode="json"),
            "prior_infrastructure_errors": [
                {
                    "reason": "RuntimeError: sandbox did not start",
                    "run_dir": "pilot/project__retried/runs/run-1",
                },
                {
                    "reason": "ConnectionError: model request failed",
                    "run_dir": "pilot/project__retried/runs/run-2",
                },
            ],
        },
    )

    report = report_module.build_report([record])

    assert [problem.reason for problem in report.infrastructure_errors] == [
        "RuntimeError: sandbox did not start",
        "ConnectionError: model request failed",
    ]
    markdown = report_module.render(report)
    section = markdown.split("## Infrastructure errors", 1)[1].split(
        "## Per instance",
        1,
    )[0]
    assert "sandbox did not start" in section
    assert "model request failed" in section
    assert "pilot/project__retried/runs/run-1" in section
    assert "pilot/project__retried/runs/run-2" in section


def test_report_lists_cleanup_errors_without_changing_instance_outcome():
    report_module = _report_module()
    record = _record(
        "project__cleanup-failed",
        [_attempt(gate_status="PASS", official_resolved=True, agreement="agree_pass")],
        verified_fix=True,
    )
    record.cleanup_error = "RuntimeError: snapshot delete denied"

    report = report_module.build_report([record])

    assert report.configuration_b.verified_fixes == 1
    assert [problem.instance_id for problem in report.cleanup_errors] == [
        "project__cleanup-failed",
    ]
    assert report.cleanup_errors[0].reason == "RuntimeError: snapshot delete denied"
    markdown = report_module.render(report)
    section = markdown.split("## Cleanup errors", 1)[1].split("## Per instance", 1)[0]
    assert "project__cleanup-failed" in section
    assert "snapshot delete denied" in section


def test_cost_columns_are_computed_from_separate_model_and_sandbox_costs():
    report_module = _report_module()
    first = _record(
        "project__first",
        [_attempt(gate_status="PASS", official_resolved=True, agreement="agree_pass")],
        verified_fix=True,
        wall_time_s=300,
    )
    first.cost = PilotCost(
        tokens=100,
        model_dollars=1.25,
        sandbox_lifetime_seconds=120,
        sandbox_dollars_estimate=0.50,
    )
    second = _record(
        "project__second",
        [_attempt()],
        wall_time_s=100,
    )
    second.cost = PilotCost(
        tokens=300,
        model_dollars=0.75,
        sandbox_lifetime_seconds=60,
        sandbox_dollars_estimate=0.25,
    )

    report = report_module.build_report([first, second])

    cost = report.configuration_b.cost_per_verified_fix
    assert cost.model_dollars == 2.0
    assert cost.sandbox_dollars_estimate == 0.75
    assert cost.total_dollars_estimate == 2.75
    assert cost.tokens == 400
    assert cost.sandbox_lifetime_seconds == 180
    assert cost.wall_time_s == 400
    markdown = report_module.render(report)
    assert (
        "| Model dollars (estimated) | Sandbox dollars (estimated) | "
        "Total dollars (estimated) | Tokens | Sandbox lifetime seconds | "
        "Wall seconds |"
    ) in markdown
    assert "Model dollars estimate Token Factory token usage." in markdown
    assert "Snapshot storage is not included" in markdown


def test_report_labels_tokenfactory_reported_sandbox_cost():
    report_module = _report_module()
    record = _record(
        "project__tokenfactory",
        [_attempt(gate_status="PASS", official_resolved=True, agreement="agree_pass")],
        verified_fix=True,
        sandbox_dollars_estimate=0.125,
    )
    record.executor_kind = "tokenfactory"

    markdown = report_module.render(report_module.build_report([record]))

    assert "Token Factory reported cost" in markdown
    assert "$0.125 Token Factory reported cost" in markdown


def test_v1_shaped_record_keeps_cost_numbers_and_daytona_wording():
    report_module = _report_module()
    original = _record(
        "project__v1",
        [_attempt(gate_status="PASS", official_resolved=True, agreement="agree_pass")],
        verified_fix=True,
        tokens=120,
        model_dollars=0.25,
        sandbox_lifetime_seconds=60,
        sandbox_dollars_estimate=0.05,
        wall_time_s=90,
    )
    payload = original.model_dump(mode="json")
    payload.pop("executor_kind", None)
    payload["cost"]["dollars"] = payload["cost"].pop("model_dollars")

    loaded = InstanceRecord.model_validate(payload)
    report = report_module.build_report([loaded])
    cost = report.configuration_b.cost_per_verified_fix

    assert loaded.executor_kind is None
    assert cost.tokens == 120
    assert cost.model_dollars == 0.25
    assert cost.sandbox_dollars_estimate == 0.05
    assert cost.total_dollars_estimate == 0.30
    assert cost.sandbox_lifetime_seconds == 60
    assert cost.wall_time_s == 90
    markdown = report_module.render(report)
    assert "estimate Daytona vCPU, memory and billable disk" in markdown
    assert "Token Factory reported cost" not in markdown


def test_report_computes_peak_live_sandboxes_and_sums_model_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    report_module = _report_module()
    monkeypatch.setattr(report_module, "_REPOSITORY_ROOT", tmp_path)
    first = _record("first", [_attempt()], run_dir="first")
    second = _record("second", [_attempt()], run_dir="second")
    missing = _record("missing", [_attempt()], run_dir="missing")
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    missing_dir = tmp_path / "missing"
    first_dir.mkdir()
    second_dir.mkdir()
    missing_dir.mkdir()
    (first_dir / "cost.json").write_text(
        json.dumps(
            {
                "sandbox_usage": [
                    {
                        "created_at": "2026-10-02T00:00:00+00:00",
                        "deleted_at": "2026-10-02T00:00:10+00:00",
                    },
                    {
                        "created_at": "2026-10-02T00:00:06+00:00",
                        "deleted_at": "2026-10-02T00:00:07+00:00",
                    },
                ],
                "model_retries": {"429": 2},
            },
        ),
        encoding="utf-8",
    )
    (second_dir / "cost.json").write_text(
        json.dumps(
            {
                "sandbox_usage": [
                    {
                        "created_at": "2026-10-02T00:00:05+00:00",
                        "deleted_at": "2026-10-02T00:00:15+00:00",
                    },
                ],
                "model_retries": {"429": 1, "5xx": 3},
            },
        ),
        encoding="utf-8",
    )

    report = report_module.build_report([first, second, missing])

    assert report.peak_live_sandboxes == 3
    assert report.peak_live_sandboxes_at == "2026-10-02T00:00:06+00:00"
    assert report.records_without_sandbox_intervals == 1
    assert report.model_retries == {"429": 3, "5xx": 3}
    markdown = report_module.render(report)
    assert "Peak live sandboxes: 3 at 2026-10-02T00:00:06+00:00." in markdown
    assert "Records without sandbox intervals: 1." in markdown
    assert "Model retries: 429: 3; 5xx: 3." in markdown


def test_headline_states_the_number_of_shipped_false_dones_when_it_is_not_zero():
    """Seen in the pilot: the pre-registered H1 and H2 sentences say "zero"; with a shipped
    false done the headline must state the real count, never "zero"."""
    report_module = _report_module()
    shipped = _record(
        "task-shipped",
        [_attempt(claimed_done=False, gate_status="PASS", official_resolved=False, agreement="gate_looser")],
        verified_fix=False,
    )

    h2 = report_module.build_report(_claimed_records(4, 40) + [shipped])
    h1 = report_module.build_report(_claimed_records(5, 50) + [shipped])

    assert h2.headline == (
        "What a verified fix costs: dollars, minutes and 1 shipped failure "
        "across 41 SWE-rebench tasks."
    )
    assert h1.headline.endswith("Receipts shipped 1.")
    assert "zero" not in h1.headline and "zero" not in h2.headline
