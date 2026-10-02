"""Build the pre-registered False-Done Report from pilot records."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from receipts.cost import DAYTONA_PRICING_READ_DATE
from receipts.models import VerdictStatus
from receipts.pilot.runner import InstanceRecord, PilotCost
from receipts.pilot.screen import ScreenRecord
from receipts.swerebench import Agreement


OfficialResult = Literal["resolved", "not_resolved", "unavailable"]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_RESULT_CLASSES = (
    "ok",
    "unknown_tool",
    "bad_args",
    "malformed_args",
    "edit_no_match",
    "edit_multiple_matches",
    "edit_too_large",
    "edit_invalid_utf8",
    "write_refused",
    "command_timeout",
    "nonzero_exit",
    "finish_refused",
    "noted",
    "not_executed",
    "tool_error",
)

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


class HarnessReport(BaseModel):
    total_tool_calls: int
    classes: dict[str, int]
    aliases: dict[str, int]
    edit_failure_rate: Rate
    not_recorded: int
    unreadable_logs: int
    unreadable_rows: int = 0
    context_guard_turns: int = 0
    context_guard_replaced_messages: int = 0
    budget_endings: dict[str, int] = Field(default_factory=dict)


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


class SpendTotal(BaseModel):
    runs: int
    tokens: int
    model_dollars: float | None
    sandbox_dollars_estimate: float
    total_dollars_estimate: float | None
    sandbox_lifetime_seconds: float
    wall_time_s: float


class SpendReport(BaseModel):
    final: SpendTotal
    infrastructure_error: SpendTotal
    interrupted: SpendTotal
    all_runs: SpendTotal
    unreadable_archives: int


class ScreeningCounts(BaseModel):
    included: int
    excluded_rule_4: int
    excluded_rule_5: int
    infrastructure_error: int
    malformed_rows: int


class ScreeningRow(BaseModel):
    position: int
    instance_id: str
    outcome: Literal["included", "excluded", "infra_error"]
    rule: Literal["4", "5"] | None
    reason: str | None
    failing_ids: list[str]
    run_number: int


class ScreeningLedgerReport(BaseModel):
    ledger: str
    counts: ScreeningCounts
    rows: list[ScreeningRow]


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


class DigestMismatch(BaseModel):
    instance_id: str
    attempt: int


class ShippedBytesReport(BaseModel):
    agree: int
    recorded: int
    not_recorded: int
    mismatches: list[DigestMismatch]


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
    executor_kind: str | None = None


class TruncatedTestIds(BaseModel):
    instance_id: str
    dataset_ids: int
    full_ids: int


class Report(BaseModel):
    headline: str
    secondary_headline: str | None
    ran_tasks: int
    spend: SpendReport
    screening: list[ScreeningLedgerReport] = Field(default_factory=list)
    configuration_a: ConfigurationA
    configuration_b: ConfigurationB
    harness: HarnessReport
    shipped_bytes: ShippedBytesReport
    agreement: AgreementReport
    exclusions: list[ReportedProblem]
    infrastructure_errors: list[ReportedProblem]
    cleanup_errors: list[ReportedProblem]
    instances: list[InstanceRow]
    truncated_test_ids: list[TruncatedTestIds] = Field(default_factory=list)
    peak_live_sandboxes: int = Field(default=0, ge=0)
    peak_live_sandboxes_at: str | None = None
    records_without_sandbox_intervals: int = Field(default=0, ge=0)
    model_retries: dict[str, int] = Field(default_factory=dict)


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
    *,
    wall_time_records: Sequence[InstanceRecord] | None = None,
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
    total_model_dollars = _total_model_dollars(records)
    sandbox_dollars = sum(
        record.cost.sandbox_dollars_estimate
        for record in records
    )
    timed_records = records if wall_time_records is None else wall_time_records
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
        wall_time_s=(
            sum(record.wall_time_s for record in timed_records)
            / verified_fixes
        ),
    )


def _total_model_dollars(records: Sequence[InstanceRecord]) -> float | None:
    values = [record.cost.model_dollars for record in records]
    if any(
        value is None and record.cost.tokens > 0
        for record, value in zip(records, values, strict=True)
    ):
        return None
    return sum(value or 0 for value in values)


def _spend_total(records: Sequence[InstanceRecord]) -> SpendTotal:
    model_dollars = _total_model_dollars(records)
    sandbox_dollars = sum(
        record.cost.sandbox_dollars_estimate
        for record in records
    )
    return SpendTotal(
        runs=len(records),
        tokens=sum(record.cost.tokens for record in records),
        model_dollars=model_dollars,
        sandbox_dollars_estimate=sandbox_dollars,
        total_dollars_estimate=(
            None
            if model_dollars is None
            else model_dollars + sandbox_dollars
        ),
        sandbox_lifetime_seconds=sum(
            record.cost.sandbox_lifetime_seconds
            for record in records
        ),
        wall_time_s=sum(record.wall_time_s for record in records),
    )


def _spend_report(
    final: Sequence[InstanceRecord],
    infrastructure_error: Sequence[InstanceRecord],
    interrupted: Sequence[InstanceRecord],
    unreadable_archives: int,
) -> SpendReport:
    all_runs = [*final, *infrastructure_error, *interrupted]
    return SpendReport(
        final=_spend_total(final),
        infrastructure_error=_spend_total(infrastructure_error),
        interrupted=_spend_total(interrupted),
        all_runs=_spend_total(all_runs),
        unreadable_archives=unreadable_archives,
    )


def _screening_report(path: Path) -> ScreeningLedgerReport:
    latest: dict[int, ScreenRecord] = {}
    malformed_rows = 0
    for line in path.read_bytes().splitlines():
        if not line.strip():
            continue
        try:
            row = ScreenRecord.model_validate_json(line)
        except (UnicodeError, ValueError):
            malformed_rows += 1
            continue
        latest[row.position] = row

    rows = [
        ScreeningRow(
            position=row.position,
            instance_id=row.instance_id,
            outcome=row.outcome,
            rule=row.rule,
            reason=row.reason,
            failing_ids=list(row.failing_ids),
            run_number=row.run_number,
        )
        for _, row in sorted(latest.items())
    ]
    return ScreeningLedgerReport(
        ledger=str(path),
        counts=ScreeningCounts(
            included=sum(row.outcome == "included" for row in rows),
            excluded_rule_4=sum(
                row.outcome == "excluded" and row.rule == "4"
                for row in rows
            ),
            excluded_rule_5=sum(
                row.outcome == "excluded" and row.rule == "5"
                for row in rows
            ),
            infrastructure_error=sum(
                row.outcome == "infra_error"
                for row in rows
            ),
            malformed_rows=malformed_rows,
        ),
        rows=rows,
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


_RESULT_FIELDS = frozenset({"id", "name", "ran_as", "executed", "class", "result_bytes"})


def _run_directory(run_dir: str) -> Path:
    """Resolve a record's run directory, including v1's absolute paths from before
    the repository moved: when such a path is gone, its part from `pilot/` on is
    looked up under the repository root."""

    path = Path(run_dir)
    if not path.is_absolute():
        return _REPOSITORY_ROOT / path
    if path.exists() or "pilot" not in path.parts:
        return path
    return _REPOSITORY_ROOT.joinpath(*path.parts[path.parts.index("pilot"):])


def _cost_artifact(record: InstanceRecord) -> dict[str, Any]:
    path = _run_directory(record.run_dir) / "cost.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _rehearsal_measurements(
    records: Sequence[InstanceRecord],
) -> tuple[int, str | None, int, dict[str, int]]:
    events: list[tuple[datetime, int]] = []
    missing_intervals = 0
    retries: dict[str, int] = {}

    for record in records:
        artifact = _cost_artifact(record)
        usage = getattr(record, "sandbox_usage", None)
        if not isinstance(usage, list):
            usage = artifact.get("sandbox_usage")
        valid_intervals = 0
        if isinstance(usage, list):
            for interval in usage:
                if not isinstance(interval, dict):
                    continue
                created_at = _utc_datetime(interval.get("created_at"))
                deleted_at = _utc_datetime(interval.get("deleted_at"))
                if created_at is None or (
                    deleted_at is not None and deleted_at < created_at
                ):
                    continue
                valid_intervals += 1
                events.append((created_at, 1))
                if deleted_at is not None:
                    events.append((deleted_at, -1))
        if valid_intervals == 0:
            missing_intervals += 1

        record_retries = getattr(record, "model_retries", None)
        if not isinstance(record_retries, dict):
            record_retries = artifact.get("model_retries")
        if isinstance(record_retries, dict):
            for kind, count in record_retries.items():
                if isinstance(kind, str) and type(count) is int and count > 0:
                    retries[kind] = retries.get(kind, 0) + count

    live = 0
    peak = 0
    peak_at: datetime | None = None
    for occurred_at, change in sorted(
        events,
        key=lambda event: (event[0], 0 if event[1] < 0 else 1),
    ):
        live += change
        if live > peak:
            peak = live
            peak_at = occurred_at
    return (
        peak,
        peak_at.isoformat() if peak_at is not None else None,
        missing_intervals,
        {kind: retries[kind] for kind in sorted(retries)},
    )


def _truncated_test_ids(
    records: Sequence[InstanceRecord],
) -> list[TruncatedTestIds]:
    found: list[TruncatedTestIds] = []
    for record in records:
        path = _run_directory(record.run_dir) / "baseline.json"
        try:
            baseline = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(baseline, dict):
            continue
        target_map = baseline.get("target_map")
        if not isinstance(target_map, dict):
            continue
        mapped = [
            (dataset_id, full_ids)
            for dataset_id, full_ids in target_map.items()
            if isinstance(dataset_id, str)
            and isinstance(full_ids, list)
            and all(isinstance(full_id, str) for full_id in full_ids)
            and full_ids != [dataset_id]
        ]
        if mapped:
            found.append(
                TruncatedTestIds(
                    instance_id=record.instance_id,
                    dataset_ids=len(mapped),
                    full_ids=sum(len(full_ids) for _, full_ids in mapped),
                ),
            )
    return found


def _valid_result(result: object) -> bool:
    return (
        isinstance(result, dict)
        and _RESULT_FIELDS <= set(result)
        and isinstance(result["id"], str)
        and isinstance(result["name"], str)
        and (result["ran_as"] is None or isinstance(result["ran_as"], str))
        and type(result["executed"]) is bool
        and result["class"] in _RESULT_CLASSES
        and type(result["result_bytes"]) is int
        and result["result_bytes"] >= 0
    )


_BUDGET_ENDING_PREFIXES = (
    ("turn budget exhausted", "turns"),
    ("wall budget exhausted", "wall_time"),
    ("completion token budget exhausted", "completion_tokens"),
)


def _budget_endings(records: Sequence[InstanceRecord]) -> dict[str, int]:
    """Count attempts that ended on a budget, by which budget ran out."""

    counts = {
        "turns": 0,
        "wall_time": 0,
        "completion_tokens": 0,
        "not_recorded": 0,
    }
    for record in records:
        for attempt in record.attempts:
            if attempt.end != "budget_exhausted":
                continue
            kind = next(
                (
                    name
                    for prefix, name in _BUDGET_ENDING_PREFIXES
                    if (attempt.end_summary or "").startswith(prefix)
                ),
                "not_recorded",
            )
            counts[kind] += 1
    return {name: counts[name] for name in sorted(counts)}


def _harness_report(records: Sequence[InstanceRecord]) -> HarnessReport:
    classes = {name: 0 for name in _RESULT_CLASSES}
    aliases: dict[str, int] = {}
    total_tool_calls = 0
    edit_calls = 0
    edit_failures = 0
    not_recorded = 0
    unreadable_logs = 0
    unreadable_rows = 0
    context_guard_turns = 0
    context_guard_replaced_messages = 0

    for record in records:
        path = _run_directory(record.run_dir) / "agent" / "worker.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            unreadable_logs += 1
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                unreadable_rows += 1
                continue
            if not isinstance(row, dict):
                unreadable_rows += 1
                continue
            context_guard = row.get("context_guard")
            if isinstance(context_guard, dict):
                replaced = context_guard.get("replaced_messages")
                if type(replaced) is int and replaced >= 0:
                    context_guard_turns += 1
                    context_guard_replaced_messages += replaced
            if "results" not in row:
                not_recorded += 1
                continue
            results = row["results"]
            if not isinstance(results, list) or not all(_valid_result(r) for r in results):
                unreadable_rows += 1
                continue
            for result in results:
                total_tool_calls += 1
                result_class = result["class"]
                classes[result_class] = classes.get(result_class, 0) + 1
                name, ran_as = result["name"], result["ran_as"]
                if ran_as is not None and name != ran_as:
                    aliases[name] = aliases.get(name, 0) + 1
                # An edit is any call meant as edit_file, aliased or not; it failed
                # unless it applied.
                if name == "edit_file" or ran_as == "edit_file":
                    edit_calls += 1
                    if result_class != "ok":
                        edit_failures += 1

    return HarnessReport(
        total_tool_calls=total_tool_calls,
        classes={name: classes[name] for name in sorted(classes)},
        aliases={name: aliases[name] for name in sorted(aliases)},
        edit_failure_rate=_rate(edit_failures, edit_calls),
        not_recorded=not_recorded,
        unreadable_logs=unreadable_logs,
        unreadable_rows=unreadable_rows,
        context_guard_turns=context_guard_turns,
        context_guard_replaced_messages=context_guard_replaced_messages,
        budget_endings=_budget_endings(records),
    )


def _headline(
    false_dones: int,
    claimed_dones: int,
    ran_tasks: int,
    shipped_false_dones: int = 0,
) -> str:
    # The pre-registered sentences say "zero"; they must state the real count otherwise.
    false_done_rate = false_dones / claimed_dones if claimed_dones else 0.0
    shipped = "zero" if shipped_false_dones == 0 else str(shipped_false_dones)
    failures = "failure" if shipped_false_dones == 1 else "failures"
    if false_dones >= 5 and false_done_rate >= 0.10:
        percent = _format_percent(false_done_rate)
        return (
            f"{percent} percent of an unguarded agent's 'done' was false; "
            f"Receipts shipped {shipped}."
        )
    return (
        f"What a verified fix costs: dollars, minutes and {shipped} shipped {failures} "
        f"across {ran_tasks} SWE-rebench tasks."
    )


def build_report(
    records: Sequence[InstanceRecord],
    *,
    infrastructure_records: Sequence[InstanceRecord] = (),
    interrupted_records: Sequence[InstanceRecord] = (),
    unreadable_archives: int = 0,
    screening: Sequence[ScreeningLedgerReport] = (),
) -> Report:
    """Compute every report value from durable per-instance records."""

    ordered = sorted(records, key=lambda record: record.instance_id)
    ran = [record for record in ordered if record.status == "ran"]
    final_infrastructure = [
        record
        for record in ordered
        if record.status == "infra_error"
    ]
    archived_infrastructure = sorted(
        infrastructure_records,
        key=lambda record: (record.instance_id, record.run_dir),
    )
    interrupted = sorted(
        interrupted_records,
        key=lambda record: (record.instance_id, record.run_dir),
    )
    all_infrastructure = [*archived_infrastructure, *final_infrastructure]
    all_spend_records = [*ran, *all_infrastructure, *interrupted]

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
    digest_recorded = 0
    digest_agree = 0
    digest_not_recorded = 0
    digest_mismatches: list[DigestMismatch] = []
    for record in ordered:
        for attempt_number, attempt in enumerate(record.attempts, start=1):
            # The bytes official grading read must match the gate's digest even when
            # it refused to apply them, so a patch changed after the gate counts as
            # a mismatch rather than as not recorded.
            official = attempt.official
            graded = [
                digest
                for digest in (
                    official.read_sha256 if official is not None else None,
                    official.applied_sha256 if official is not None else None,
                )
                if digest is not None
            ]
            if (
                attempt.filtered_sha256 is None
                or attempt.witness_apply_sha256 is None
                or not graded
            ):
                digest_not_recorded += 1
            else:
                digest_recorded += 1
                digests = {attempt.filtered_sha256, attempt.witness_apply_sha256, *graded}
                if len(digests) == 1:
                    digest_agree += 1
                else:
                    digest_mismatches.append(
                        DigestMismatch(
                            instance_id=record.instance_id,
                            attempt=attempt_number,
                        ),
                    )
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
    infrastructure_errors = []
    for record in ordered:
        infrastructure_errors.extend(
            ReportedProblem(
                instance_id=record.instance_id,
                reason=prior.reason,
                run_dir=prior.run_dir,
            )
            for prior in record.prior_infrastructure_errors
        )
        if record.status == "infra_error":
            infrastructure_errors.append(
                ReportedProblem(
                    instance_id=record.instance_id,
                    reason=record.reason or "reason unavailable",
                    run_dir=record.run_dir,
                ),
            )
    cleanup_errors = [
        ReportedProblem(
            instance_id=record.instance_id,
            reason=record.cleanup_error,
            run_dir=record.run_dir,
        )
        for record in ordered
        if record.cleanup_error is not None
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
                executor_kind=record.executor_kind,
            ),
        )

    verified_fixes = len(verified_records)
    ran_tasks = len(ran)
    verified_rate = _rate(verified_fixes, ran_tasks)
    peak, peak_at, missing_intervals, model_retries = _rehearsal_measurements(
        ordered,
    )
    secondary_headline = None
    if verified_rate.value is not None and verified_rate.value < 0.15:
        secondary_headline = _H3

    return Report(
        headline=_headline(len(false_done_attempts), len(claimed), ran_tasks, shipped_false_dones),
        secondary_headline=secondary_headline,
        ran_tasks=ran_tasks,
        spend=_spend_report(
            ran,
            all_infrastructure,
            interrupted,
            unreadable_archives,
        ),
        screening=list(screening),
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
            cost_per_verified_fix=_cost_per_verified_fix(
                all_spend_records,
                verified_fixes,
                wall_time_records=ran,
            ),
        ),
        harness=_harness_report(ordered),
        shipped_bytes=ShippedBytesReport(
            agree=digest_agree,
            recorded=digest_recorded,
            not_recorded=digest_not_recorded,
            mismatches=digest_mismatches,
        ),
        agreement=AgreementReport(
            matrix=matrix,
            disagreements=disagreements,
        ),
        exclusions=exclusions,
        infrastructure_errors=infrastructure_errors,
        cleanup_errors=cleanup_errors,
        instances=instances,
        truncated_test_ids=_truncated_test_ids(ordered),
        peak_live_sandboxes=peak,
        peak_live_sandboxes_at=peak_at,
        records_without_sandbox_intervals=missing_intervals,
        model_retries=model_retries,
    )


def _load_archives(
    paths: Sequence[Path],
) -> tuple[list[InstanceRecord], int]:
    records: list[InstanceRecord] = []
    unreadable = 0
    for path in paths:
        try:
            records.append(InstanceRecord.model_validate_json(path.read_bytes()))
        except (OSError, UnicodeError, ValueError):
            unreadable += 1
    return records, unreadable


def build_report_from_directory(
    pilot_dir: Path,
    *,
    screen_ledgers: Sequence[Path] = (),
) -> Report:
    """Load final and archived records, then compute the report."""

    records = [
        InstanceRecord.model_validate_json(path.read_bytes())
        for path in sorted(pilot_dir.glob("*/record.json"))
    ]
    infrastructure, unreadable_infrastructure = _load_archives(
        sorted(pilot_dir.glob("*/record.infra-*.json")),
    )
    interrupted, unreadable_interrupted = _load_archives(
        sorted(pilot_dir.glob("*/record.interrupted-*.json")),
    )
    screening = [_screening_report(path) for path in screen_ledgers]
    return build_report(
        records,
        infrastructure_records=infrastructure,
        interrupted_records=interrupted,
        unreadable_archives=(
            unreadable_infrastructure + unreadable_interrupted
        ),
        screening=screening,
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


def _format_dollars(value: float | None) -> str:
    if value is None:
        return "not available"
    return f"${_format_number(value)}"


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


def _screening_outcome(row: ScreeningRow) -> str:
    if row.outcome == "included":
        return "included"
    if row.outcome == "infra_error":
        return "final infrastructure error"
    if row.rule in {"4", "5"}:
        return f"excluded under rule {row.rule}"
    return "excluded"


def _render_screening(screening: Sequence[ScreeningLedgerReport]) -> list[str]:
    if not screening:
        return []
    lines = ["## Screening", ""]
    for ledger in screening:
        counts = ledger.counts
        lines.extend(
            [
                f"### `{_cell(ledger.ledger)}`",
                "",
                (
                    f"Included: {counts.included}; "
                    f"rule 4 exclusions: {counts.excluded_rule_4}; "
                    f"rule 5 exclusions: {counts.excluded_rule_5}; "
                    f"final infrastructure errors: {counts.infrastructure_error}; "
                    f"malformed rows: {counts.malformed_rows}."
                ),
                "",
                "| Position | Instance | Result | Reason | Failing ids |",
                "| ---: | --- | --- | --- | --- |",
            ],
        )
        lines.extend(
            (
                f"| {row.position} | {_cell(row.instance_id)} | "
                f"{_screening_outcome(row)} | "
                f"{_cell(row.reason or '')} | "
                f"{_cell(', '.join(row.failing_ids))} |"
            )
            for row in ledger.rows
        )
        lines.append("")
    return lines


_TOKENFACTORY_SANDBOX_COST_HEADER = (
    "Token Factory reported sandbox cost (unit not published)"
)
_TOKENFACTORY_SANDBOX_COST_NOTE = (
    "The sandbox figure is the per-run `cost` that Token Factory Sandboxes "
    "report. Token Factory does not publish the unit or a price during the "
    "beta, so the figure is shown as reported, not as dollars, and no dollar "
    "total is given."
)


def _has_tokenfactory(report: Report) -> bool:
    return any(row.executor_kind == "tokenfactory" for row in report.instances)


def _render_budget_endings(counts: dict[str, int]) -> str:
    return (
        "Attempts that ended on a budget: "
        f"{counts.get('turns', 0)} on turns, "
        f"{counts.get('wall_time', 0)} on wall time, "
        f"{counts.get('completion_tokens', 0)} on completion tokens, "
        f"{counts.get('not_recorded', 0)} not recorded."
    )


def _render_spend(spend: SpendReport, *, tokenfactory: bool = False) -> list[str]:
    if tokenfactory:
        lines = [
            "## Spend",
            "",
            f"| Run class | Runs | Model dollars | {_TOKENFACTORY_SANDBOX_COST_HEADER} |",
            "| --- | ---: | ---: | ---: |",
        ]
    else:
        lines = [
            "## Spend",
            "",
            "| Run class | Runs | Model dollars | Sandbox dollars | Total dollars |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    for label, total in (
        ("Final", spend.final),
        ("Infrastructure error", spend.infrastructure_error),
        ("Interrupted", spend.interrupted),
        ("All runs", spend.all_runs),
    ):
        if tokenfactory:
            lines.append(
                f"| {label} | {total.runs} | "
                f"{_format_dollars(total.model_dollars)} | "
                f"{_format_number(total.sandbox_dollars_estimate)} |",
            )
        else:
            lines.append(
                f"| {label} | {total.runs} | "
                f"{_format_dollars(total.model_dollars)} | "
                f"{_format_dollars(total.sandbox_dollars_estimate)} | "
                f"{_format_dollars(total.total_dollars_estimate)} |",
            )
    lines.extend(
        [
            "",
            f"Unreadable archives: {spend.unreadable_archives}.",
            "All runs includes final agent runs and every readable "
            "infrastructure-error and interrupted archive.",
        ],
    )
    if tokenfactory:
        lines.append(_TOKENFACTORY_SANDBOX_COST_NOTE)
    lines.append("")
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
    if report.truncated_test_ids:
        rendered = "; ".join(
            f"{item.instance_id} "
            f"({item.dataset_ids} dataset "
            f"{'id' if item.dataset_ids == 1 else 'ids'}, "
            f"{item.full_ids} full {'id' if item.full_ids == 1 else 'ids'})"
            for item in report.truncated_test_ids
        )
        lines.extend([f"Truncated test ids: {rendered}.", ""])

    lines.extend(_render_screening(report.screening))
    lines.extend(_render_spend(report.spend, tokenfactory=_has_tokenfactory(report)))

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
    has_tokenfactory = _has_tokenfactory(report)
    has_daytona_or_legacy = any(
        row.executor_kind != "tokenfactory"
        for row in report.instances
    )
    if has_tokenfactory and has_daytona_or_legacy:
        sandbox_cost_explanation = (
            "Model dollars estimate Token Factory token usage. The sandbox figure "
            "adds Token Factory reported cost for Token Factory runs to Daytona "
            "dollar estimates for the others, so it has no single unit. "
            + _TOKENFACTORY_SANDBOX_COST_NOTE
        )
    elif has_tokenfactory:
        sandbox_cost_explanation = (
            "Model dollars estimate Token Factory token usage. "
            + _TOKENFACTORY_SANDBOX_COST_NOTE
        )
    else:
        sandbox_cost_explanation = (
            "Model dollars estimate Token Factory token usage. Sandbox dollars "
            "estimate Daytona vCPU, memory and billable disk over measured "
            "sandbox lifetimes. Total dollars combines both estimates."
        )
    cost_notes = [
        (
            "Model dollars, sandbox cost, tokens and sandbox lifetime use "
            "all readable final, infrastructure-error and interrupted runs."
        ),
        "",
        sandbox_cost_explanation,
        "",
    ]
    if has_daytona_or_legacy:
        cost_notes.extend(
            [
                "Snapshot storage is not included because Daytona had not published "
                f"its price when the rates were read on {DAYTONA_PRICING_READ_DATE}.",
                "",
            ],
        )
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
            *cost_notes,
        ],
    )
    if has_tokenfactory:
        lines.extend(
            [
                "| Model dollars (estimated) | "
                f"{_TOKENFACTORY_SANDBOX_COST_HEADER} | Tokens | "
                "Sandbox lifetime seconds | Wall seconds |",
                "| ---: | ---: | ---: | ---: | ---: |",
                (
                    f"| {_format_number(cost.model_dollars)} | "
                    f"{_format_number(cost.sandbox_dollars_estimate)} | "
                    f"{_format_number(cost.tokens)} | "
                    f"{_format_number(cost.sandbox_lifetime_seconds)} | "
                    f"{_format_number(cost.wall_time_s)} |"
                ),
            ],
        )
    else:
        lines.extend(
            [
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
            ],
        )

    peak_line = f"Peak live sandboxes: {report.peak_live_sandboxes}"
    if report.peak_live_sandboxes_at is not None:
        peak_line += f" at {report.peak_live_sandboxes_at}"
    retry_text = "; ".join(
        f"{kind}: {count}"
        for kind, count in report.model_retries.items()
    ) or "none"
    lines.extend(
        [
            "",
            "### Rehearsal measurements",
            "",
            peak_line + ".",
            "",
            (
                "Records without sandbox intervals: "
                f"{report.records_without_sandbox_intervals}."
            ),
            "",
            f"Model retries: {retry_text}.",
        ],
    )

    harness = report.harness
    edit_rate = harness.edit_failure_rate
    edit_rate_text = f"{edit_rate.numerator} of {edit_rate.denominator}"
    if edit_rate.value is not None:
        edit_rate_text += f" ({_format_percent(edit_rate.value)}%)"
    lines.extend(
        [
            "",
            "## Harness",
            "",
            f"Total tool calls: {harness.total_tool_calls}.",
            "",
            f"Edit-failure rate (edit calls that did not apply, over all edit calls): {edit_rate_text}.",
            "",
            (
                f"Context guard: {harness.context_guard_turns} "
                f"{'turn' if harness.context_guard_turns == 1 else 'turns'}; "
                f"{harness.context_guard_replaced_messages} "
                f"{'message' if harness.context_guard_replaced_messages == 1 else 'messages'} "
                "replaced."
            ),
            "",
            _render_budget_endings(harness.budget_endings),
            "",
            (
                f"{harness.not_recorded} "
                f"{'turn' if harness.not_recorded == 1 else 'turns'} not recorded "
                "(worker rows before result logging)."
            ),
            "",
            (
                f"{harness.unreadable_logs} worker "
                f"{'log' if harness.unreadable_logs == 1 else 'logs'} "
                "unreadable or missing; "
                f"{harness.unreadable_rows} unreadable "
                f"{'row' if harness.unreadable_rows == 1 else 'rows'} skipped."
            ),
            "",
            "### Result classes",
            "",
            "| Class | Calls |",
            "| --- | ---: |",
        ],
    )
    lines.extend(
        f"| {name} | {count} |"
        for name, count in harness.classes.items()
    )
    lines.extend(["", "### Alias calls", ""])
    if harness.aliases:
        lines.extend(["| Alias | Calls |", "| --- | ---: |"])
        lines.extend(
            f"| {name} | {count} |"
            for name, count in harness.aliases.items()
        )
    else:
        lines.append("None.")

    lines.extend(
        [
            "",
            "## Shipped bytes",
            "",
            (
                "Shipped bytes: digests agree on "
                f"{report.shipped_bytes.agree} of "
                f"{report.shipped_bytes.recorded} attempts."
            ),
            "",
            (
                f"{report.shipped_bytes.not_recorded} "
                f"{'attempt' if report.shipped_bytes.not_recorded == 1 else 'attempts'} "
                "not recorded (records before this check)."
            ),
            "",
        ],
    )
    if report.shipped_bytes.mismatches:
        lines.extend(
            [
                "| Instance | Attempt |",
                "| --- | ---: |",
            ],
        )
        lines.extend(
            f"| {_cell(item.instance_id)} | {item.attempt} |"
            for item in report.shipped_bytes.mismatches
        )
    else:
        lines.append("Mismatches: none.")
    lines.extend(
        [
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
    lines.extend(["", "## Cleanup errors", ""])
    lines.extend(_render_problem_table(report.cleanup_errors))

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
        if row.executor_kind == "tokenfactory":
            cost_parts = [
                f"{_format_number(row.cost.sandbox_dollars_estimate)} "
                "Token Factory reported cost, unit not published",
            ]
        else:
            cost_parts = [
                f"${_format_number(row.cost.sandbox_dollars_estimate)} "
                "sandbox estimated",
                f"{total_dollars} total estimated",
            ]
        rendered_cost = "; ".join(
            [
                f"{row.cost.tokens} tokens",
                f"{model_dollars} model estimated",
                *cost_parts,
                f"{_format_number(row.cost.sandbox_lifetime_seconds)} sandbox lifetime s",
                f"{_format_number(row.wall_time_s)} wall s",
            ],
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


__all__ = ["Report", "build_report", "build_report_from_directory", "render"]
