"""Build the pre-registered False-Done Report from pilot records."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from receipts.cost import DAYTONA_PRICING_READ_DATE
from receipts.models import VerdictStatus
from receipts.pilot.runner import InstanceRecord, PilotCost
from receipts.swerebench import Agreement


OfficialResult = Literal["resolved", "not_resolved", "unavailable"]

_BREAKDOWN_PREDICATES = {
    "spec_still_failing": "R1_fail_to_pass",
    "regression": "R2_pass_to_pass",
    "tests_removed_or_newly_skipped": "R3_no_shrink",
    "test_or_config_edited": "R4_patch_scope",
}
_BREAKDOWN_LABELS = {
    "spec_still_failing": "Spec still failing (R1)",
    "regression": "Regression (R2)",
    "tests_removed_or_newly_skipped": "Tests removed or newly skipped (R3)",
    "test_or_config_edited": "Test or config edited (R4)",
    "tests_never_run_on_final_state": "Tests never run on the final state",
}
_GATE_STATUSES: tuple[VerdictStatus, ...] = ("PASS", "REJECTED", "ERROR")
_OFFICIAL_RESULTS: tuple[OfficialResult, ...] = (
    "resolved",
    "not_resolved",
    "unavailable",
)
_H3 = (
    "Knowing when not to ship: every unverified patch was refused, "
    "with the evidence published."
)


class Rate(BaseModel):
    numerator: int
    denominator: int
    value: float | None
    lower_95: float | None
    upper_95: float | None


class ConfigurationA(BaseModel):
    claimed_dones: int
    false_dones: int
    false_done_rate: Rate
    breakdown: dict[str, int]
    naive_green_false_dones: int


class CostPerVerifiedFix(BaseModel):
    tokens: float | None
    model_dollars: float | None
    sandbox_dollars_estimate: float | None
    total_dollars_estimate: float | None
    sandbox_lifetime_seconds: float | None
    wall_time_s: float | None


class ConfigurationB(BaseModel):
    verified_fixes: int
    first_verdict: int
    appeal: int
    shipped_false_dones: int
    verified_rate: Rate
    cost_per_verified_fix: CostPerVerifiedFix


class Disagreement(BaseModel):
    instance_id: str
    attempt: int
    agreement: Agreement
    failed_predicate_ids: list[str]
    gate_error: str | None


class AgreementReport(BaseModel):
    matrix: dict[str, dict[str, int]]
    disagreements: list[Disagreement]


class ReportedProblem(BaseModel):
    instance_id: str
    reason: str
    run_dir: str


class InstanceRow(BaseModel):
    instance_id: str
    a_claimed_done: bool
    a_official_resolved: bool | None
    b_outcome: str
    b_official_resolved: bool | None
    cost: PilotCost
    wall_time_s: float
    run_dir: str


class Report(BaseModel):
    headline: str
    secondary_headline: str | None
    ran_tasks: int
    configuration_a: ConfigurationA
    configuration_b: ConfigurationB
    agreement: AgreementReport
    exclusions: list[ReportedProblem]
    infrastructure_errors: list[ReportedProblem]
    instances: list[InstanceRow]


def _rate(numerator: int, denominator: int) -> Rate:
    if denominator == 0:
        return Rate(
            numerator=numerator,
            denominator=denominator,
            value=None,
            lower_95=None,
            upper_95=None,
        )
    value = numerator / denominator
    z = 1.959963984540054
    z_squared = z * z
    scale = 1 + z_squared / denominator
    center = (value + z_squared / (2 * denominator)) / scale
    margin = (
        z
        * math.sqrt(
            value * (1 - value) / denominator
            + z_squared / (4 * denominator * denominator),
        )
        / scale
    )
    return Rate(
        numerator=numerator,
        denominator=denominator,
        value=value,
        lower_95=max(0.0, center - margin),
        upper_95=min(1.0, center + margin),
    )


def _official_result(resolved: bool | None) -> OfficialResult:
    if resolved is True:
        return "resolved"
    if resolved is False:
        return "not_resolved"
    return "unavailable"


def _cost_per_verified_fix(
    records: Sequence[InstanceRecord],
    verified_fixes: int,
) -> CostPerVerifiedFix:
    if verified_fixes == 0:
        return CostPerVerifiedFix(
            tokens=None,
            model_dollars=None,
            sandbox_dollars_estimate=None,
            total_dollars_estimate=None,
            sandbox_lifetime_seconds=None,
            wall_time_s=None,
        )
    model_dollars = [record.cost.model_dollars for record in records]
    total_model_dollars = (
        None
        if any(value is None for value in model_dollars)
        else sum(model_dollars)
    )
    sandbox_dollars = sum(
        record.cost.sandbox_dollars_estimate
        for record in records
    )
    return CostPerVerifiedFix(
        tokens=sum(record.cost.tokens for record in records) / verified_fixes,
        model_dollars=(
            None
            if total_model_dollars is None
            else total_model_dollars / verified_fixes
        ),
        sandbox_dollars_estimate=sandbox_dollars / verified_fixes,
        total_dollars_estimate=(
            None
            if total_model_dollars is None
            else (total_model_dollars + sandbox_dollars) / verified_fixes
        ),
        sandbox_lifetime_seconds=(
            sum(record.cost.sandbox_lifetime_seconds for record in records)
            / verified_fixes
        ),
        wall_time_s=sum(record.wall_time_s for record in records) / verified_fixes,
    )


def _b_outcome(record: InstanceRecord) -> str:
    if record.status == "excluded":
        return "excluded"
    if record.status == "infra_error":
        return "infrastructure error"
    if record.final is None:
        return "not run"
    if record.final.verified_fix:
        if len(record.attempts) == 1:
            return "verified on first verdict"
        return "verified on appeal"
    if (
        record.final.gate_status == "PASS"
        and record.final.official_resolved is False
    ):
        return "shipped false done"
    if record.final.gate_status == "ERROR":
        return "gate error"
    return "refused"


def _headline(
    false_dones: int,
    claimed_dones: int,
    ran_tasks: int,
) -> str:
    false_done_rate = false_dones / claimed_dones if claimed_dones else 0.0
    if false_dones >= 5 and false_done_rate >= 0.10:
        percent = _format_percent(false_done_rate)
        return (
            f"{percent} percent of an unguarded agent's 'done' was false; "
            "Receipts shipped zero."
        )
    return (
        "What a verified fix costs: dollars, minutes and zero shipped failures "
        f"across {ran_tasks} SWE-rebench tasks."
    )


def build_report(records: Sequence[InstanceRecord]) -> Report:
    """Compute every report value from durable per-instance records."""

    ordered = sorted(records, key=lambda record: record.instance_id)
    ran = [record for record in ordered if record.status == "ran"]

    first_attempts = [record.attempts[0] for record in ran if record.attempts]
    claimed = [attempt for attempt in first_attempts if attempt.claimed_done]
    false_done_attempts = [
        attempt
        for attempt in claimed
        if attempt.official_resolved is False
    ]
    breakdown = {
        name: sum(
            predicate in attempt.failed_predicate_ids
            for attempt in false_done_attempts
        )
        for name, predicate in _BREAKDOWN_PREDICATES.items()
    }
    breakdown["tests_never_run_on_final_state"] = sum(
        attempt.claim_audit == "unsupported"
        for attempt in false_done_attempts
    )

    verified_records = [
        record
        for record in ran
        if record.final is not None and record.final.verified_fix
    ]
    first_verdict = sum(len(record.attempts) == 1 for record in verified_records)
    appeals = sum(len(record.attempts) > 1 for record in verified_records)
    shipped_false_dones = sum(
        record.final is not None
        and record.final.gate_status == "PASS"
        and record.final.official_resolved is False
        for record in ran
    )

    matrix = {
        gate_status: {official: 0 for official in _OFFICIAL_RESULTS}
        for gate_status in _GATE_STATUSES
    }
    disagreements: list[Disagreement] = []
    for record in ordered:
        for attempt_number, attempt in enumerate(record.attempts, start=1):
            matrix[attempt.gate_status][
                _official_result(attempt.official_resolved)
            ] += 1
            if attempt.gate_status == "ERROR" or attempt.agreement in {
                "gate_looser",
                "gate_stricter",
                "gate_error",
            }:
                disagreements.append(
                    Disagreement(
                        instance_id=record.instance_id,
                        attempt=attempt_number,
                        agreement=(
                            "gate_error"
                            if attempt.gate_status == "ERROR"
                            else attempt.agreement
                        ),
                        failed_predicate_ids=list(attempt.failed_predicate_ids),
                        gate_error=attempt.gate_error,
                    ),
                )

    exclusions = [
        ReportedProblem(
            instance_id=record.instance_id,
            reason=record.reason or "reason unavailable",
            run_dir=record.run_dir,
        )
        for record in ordered
        if record.status == "excluded"
    ]
    infrastructure_errors = [
        ReportedProblem(
            instance_id=record.instance_id,
            reason=record.reason or "reason unavailable",
            run_dir=record.run_dir,
        )
        for record in ordered
        if record.status == "infra_error"
    ]
    instances = []
    for record in ordered:
        first = record.attempts[0] if record.attempts else None
        instances.append(
            InstanceRow(
                instance_id=record.instance_id,
                a_claimed_done=first.claimed_done if first is not None else False,
                a_official_resolved=(
                    first.official_resolved if first is not None else None
                ),
                b_outcome=_b_outcome(record),
                b_official_resolved=(
                    record.final.official_resolved
                    if record.final is not None
                    else None
                ),
                cost=record.cost,
                wall_time_s=record.wall_time_s,
                run_dir=record.run_dir,
            ),
        )

    verified_fixes = len(verified_records)
    ran_tasks = len(ran)
    verified_rate = _rate(verified_fixes, ran_tasks)
    secondary_headline = None
    if verified_rate.value is not None and verified_rate.value < 0.15:
        secondary_headline = _H3

    return Report(
        headline=_headline(len(false_done_attempts), len(claimed), ran_tasks),
        secondary_headline=secondary_headline,
        ran_tasks=ran_tasks,
        configuration_a=ConfigurationA(
            claimed_dones=len(claimed),
            false_dones=len(false_done_attempts),
            false_done_rate=_rate(len(false_done_attempts), len(claimed)),
            breakdown=breakdown,
            naive_green_false_dones=sum(
                attempt.naive_green for attempt in false_done_attempts
            ),
        ),
        configuration_b=ConfigurationB(
            verified_fixes=verified_fixes,
            first_verdict=first_verdict,
            appeal=appeals,
            shipped_false_dones=shipped_false_dones,
            verified_rate=verified_rate,
            cost_per_verified_fix=_cost_per_verified_fix(ran, verified_fixes),
        ),
        agreement=AgreementReport(
            matrix=matrix,
            disagreements=disagreements,
        ),
        exclusions=exclusions,
        infrastructure_errors=infrastructure_errors,
        instances=instances,
    )


def _format_percent(value: float) -> str:
    percent = value * 100
    if math.isclose(percent, round(percent), abs_tol=1e-9):
        return str(round(percent))
    return f"{percent:.1f}".rstrip("0").rstrip(".")


def _format_number(value: float | None) -> str:
    if value is None:
        return "not available"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _official_label(value: bool | None) -> str:
    return {
        True: "resolved",
        False: "not resolved",
        None: "unavailable",
    }[value]


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _render_rate(rate: Rate) -> str:
    if rate.value is None or rate.lower_95 is None or rate.upper_95 is None:
        return f"not available ({rate.numerator} of {rate.denominator})"
    return (
        f"{_format_percent(rate.value)}% ({rate.numerator} of {rate.denominator}), "
        f"Wilson 95% CI {_format_percent(rate.lower_95)}% to "
        f"{_format_percent(rate.upper_95)}%"
    )


def _render_problem_table(problems: Sequence[ReportedProblem]) -> list[str]:
    if not problems:
        return ["None."]
    lines = [
        "| Instance | Reason | Run directory |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {_cell(problem.instance_id)} | {_cell(problem.reason)} | "
        f"`{_cell(problem.run_dir)}` |"
        for problem in problems
    )
    return lines


def render(report: Report) -> str:
    """Render a deterministic Markdown report from computed report data."""

    lines: list[str] = []
    shipped = report.configuration_b.shipped_false_dones
    if shipped:
        noun = "done" if shipped == 1 else "dones"
        lines.extend([f"Receipts shipped {shipped} false {noun}.", ""])

    lines.extend([f"# {report.headline}", ""])
    if report.secondary_headline is not None:
        lines.extend([f"## {report.secondary_headline}", ""])

    configuration_a = report.configuration_a
    lines.extend(
        [
            "## Unguarded agent (A)",
            "",
            f"Claimed dones: {configuration_a.claimed_dones}.",
            "",
            f"False-done rate: {_render_rate(configuration_a.false_done_rate)}.",
            "",
            (
                "False dones accepted by the naive green check: "
                f"{configuration_a.naive_green_false_dones}."
            ),
            "",
            "A false done can appear in more than one breakdown row.",
            "",
            "| Kind | False dones |",
            "| --- | ---: |",
        ],
    )
    lines.extend(
        f"| {_BREAKDOWN_LABELS[name]} | {configuration_a.breakdown[name]} |"
        for name in _BREAKDOWN_LABELS
    )

    configuration_b = report.configuration_b
    cost = configuration_b.cost_per_verified_fix
    lines.extend(
        [
            "",
            "## Receipts (B)",
            "",
            "| Result | Count |",
            "| --- | ---: |",
            f"| Verified fixes | {configuration_b.verified_fixes} |",
            f"| Verified on first verdict | {configuration_b.first_verdict} |",
            f"| Verified on appeal | {configuration_b.appeal} |",
            f"| Shipped false dones | {configuration_b.shipped_false_dones} |",
            "",
            f"Verified-fix rate: {_render_rate(configuration_b.verified_rate)}.",
            "",
            "### Cost per verified fix",
            "",
            (
                "Model dollars estimate Token Factory token usage. Sandbox dollars "
                "estimate Daytona vCPU, memory and billable disk over measured "
                "sandbox lifetimes. Total dollars combines both estimates."
            ),
            "",
            (
                "Snapshot storage is not included because Daytona had not published "
                f"its price when the rates were read on {DAYTONA_PRICING_READ_DATE}."
            ),
            "",
            "| Model dollars (estimated) | Sandbox dollars (estimated) | "
            "Total dollars (estimated) | Tokens | Sandbox lifetime seconds | "
            "Wall seconds |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
            (
                f"| {_format_number(cost.model_dollars)} | "
                f"{_format_number(cost.sandbox_dollars_estimate)} | "
                f"{_format_number(cost.total_dollars_estimate)} | "
                f"{_format_number(cost.tokens)} | "
                f"{_format_number(cost.sandbox_lifetime_seconds)} | "
                f"{_format_number(cost.wall_time_s)} |"
            ),
            "",
            "## Gate and official-grader agreement",
            "",
            "| Gate status | Official resolved | Official not resolved | "
            "Official unavailable |",
            "| --- | ---: | ---: | ---: |",
        ],
    )
    lines.extend(
        f"| {gate_status} | {report.agreement.matrix[gate_status]['resolved']} | "
        f"{report.agreement.matrix[gate_status]['not_resolved']} | "
        f"{report.agreement.matrix[gate_status]['unavailable']} |"
        for gate_status in _GATE_STATUSES
    )
    lines.extend(["", "### Disagreements and gate errors", ""])
    if report.agreement.disagreements:
        lines.extend(
            [
                "| Instance | Attempt | Classification | Failed predicates | "
                "Gate error |",
                "| --- | ---: | --- | --- | --- |",
            ],
        )
        lines.extend(
            f"| {_cell(item.instance_id)} | {item.attempt} | {item.agreement} | "
            f"{_cell(', '.join(item.failed_predicate_ids) or 'none')} | "
            f"{_cell(item.gate_error or 'none')} |"
            for item in report.agreement.disagreements
        )
    else:
        lines.append("None.")

    lines.extend(["", "## Exclusions", ""])
    lines.extend(_render_problem_table(report.exclusions))
    lines.extend(["", "## Infrastructure errors", ""])
    lines.extend(_render_problem_table(report.infrastructure_errors))

    lines.extend(
        [
            "",
            "## Per instance",
            "",
            "| Instance | A claimed done | A official | B outcome | B official | "
            "Cost | Run directory |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ],
    )
    for row in report.instances:
        model_dollars = (
            "not available"
            if row.cost.model_dollars is None
            else f"${_format_number(row.cost.model_dollars)}"
        )
        total_dollars = (
            "not available"
            if row.cost.model_dollars is None
            else "$"
            + _format_number(
                row.cost.model_dollars + row.cost.sandbox_dollars_estimate,
            )
        )
        rendered_cost = (
            f"{row.cost.tokens} tokens; {model_dollars} model estimated; "
            f"${_format_number(row.cost.sandbox_dollars_estimate)} sandbox estimated; "
            f"{total_dollars} total estimated; "
            f"{_format_number(row.cost.sandbox_lifetime_seconds)} sandbox lifetime s; "
            f"{_format_number(row.wall_time_s)} wall s"
        )
        lines.append(
            f"| {_cell(row.instance_id)} | "
            f"{'yes' if row.a_claimed_done else 'no'} | "
            f"{_official_label(row.a_official_resolved)} | "
            f"{_cell(row.b_outcome)} | "
            f"{_official_label(row.b_official_resolved)} | "
            f"{rendered_cost} | `{_cell(row.run_dir)}` |"
        )

    return "\n".join(lines) + "\n"


__all__ = ["Report", "build_report", "render"]
