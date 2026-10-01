from __future__ import annotations

from collections.abc import Sequence

import pytest

from receipts.pilot.runner import (
    AttemptRecord,
    FinalRecord,
    InstanceRecord,
    PilotCost,
)


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
        gate_error=gate_error,
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
        run_dir=f"pilot/{instance_id}/runs/run-1",
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
