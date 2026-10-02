"""Replay the current receipt gate over stored pilot attempts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel

from receipts.models import (
    Baseline,
    PatchScope,
    Receipt,
    Verdict,
    VerdictStatus,
)
from receipts.orchestrate import AttemptResult, RunResult
from receipts.patchscope import default_protected_modules, summarize_patch
from receipts.pilot.runner import AttemptRecord, InstanceRecord
from receipts.swerebench import Instance
from receipts.verify.gate import evaluate
from receipts.verify.targets import map_target_ids


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_STATUSES: tuple[VerdictStatus, ...] = ("PASS", "REJECTED", "ERROR")


class ReplayAttempt(BaseModel):
    record_set: str
    instance_id: str
    attempt: int
    v1_status: VerdictStatus
    v1_failed_predicate_ids: list[str]
    v2_status: VerdictStatus
    v2_failed_predicate_ids: list[str]
    official_resolved: bool | None
    status_changed: bool
    scope: Literal["inferred"] = "inferred"
    load_failure: Literal["assumed reproduced"] | None = None


class ReplaySummary(BaseModel):
    v1_status_counts: dict[str, int]
    v2_status_counts: dict[str, int]
    became_pass: list[ReplayAttempt]
    became_rejected: list[ReplayAttempt]
    stopped_being_error: list[ReplayAttempt]
    new_gate_looser: list[ReplayAttempt]
    pre_existing_unresolved_pass: list[ReplayAttempt]


class ReplayReport(BaseModel):
    attempts: list[ReplayAttempt]
    summary: ReplaySummary


def _run_directory(run_dir: str, record_path: Path | None = None) -> Path:
    """Resolve old absolute run paths from their repository-local pilot suffix."""

    path = Path(run_dir)
    if not path.is_absolute():
        resolved = _REPOSITORY_ROOT / path
    elif path.exists() or "pilot" not in path.parts:
        resolved = path
    else:
        resolved = _REPOSITORY_ROOT.joinpath(
            *path.parts[path.parts.index("pilot"):],
        )
    if resolved.exists() or record_path is None:
        return resolved
    selected_copy = record_path.parent / "runs" / path.name
    return selected_copy if selected_copy.exists() else resolved


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _read_receipts(path: Path) -> list[Receipt]:
    return [
        Receipt.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _record_paths(run_dirs: Sequence[Path]) -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    for root in run_dirs:
        direct = root / "record.json"
        selected = [direct] if direct.is_file() else sorted(root.glob("*/record.json"))
        paths.extend((root.name, path) for path in selected)
    return paths


def _load_instances(data_path: Path, wanted: set[str]) -> dict[str, Instance]:
    instances: dict[str, Instance] = {}
    for line_number, line in enumerate(
        data_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"dataset row {line_number} is not a JSON object")
        instance_id = value.get("instance_id")
        if instance_id not in wanted:
            continue
        if instance_id in instances:
            raise ValueError(f"duplicate dataset row for {instance_id}")
        value.pop("patch", None)
        instances[instance_id] = Instance.model_validate(value)
    missing = sorted(wanted.difference(instances))
    if missing:
        raise ValueError("instances missing from dataset: " + ", ".join(missing))
    return instances


def _top_level_entry(path: str) -> tuple[str, str] | None:
    parts = path.split("/")
    if not parts or not parts[0]:
        return None
    if len(parts) >= 2 and parts[0] == "src":
        entry = f"src/{parts[1]}"
        name = parts[1]
    else:
        entry = parts[0]
        name = parts[0]
    return entry, PurePosixPath(name).stem


def _inferred_scope(
    c0_paths: Iterable[str],
    protected_modules: frozenset[str],
) -> PatchScope:
    entries: set[str] = set()
    names = set(protected_modules)
    for path in c0_paths:
        item = _top_level_entry(path)
        if item is None:
            continue
        entry, name = item
        entries.add(entry)
        names.add(name)
    return PatchScope(
        protected_names=sorted(names),
        c0_top_level=sorted(entries),
    )


def _v2_baseline(
    stored: Baseline,
    instance: Instance,
    scope: PatchScope,
) -> Baseline:
    target_map = map_target_ids(instance.fail_to_pass, stored.collected_ids)
    targets = list(
        dict.fromkeys(
            node_id
            for dataset_id in instance.fail_to_pass
            for node_id in target_map[dataset_id]
        ),
    )
    test_patch_paths = [
        changed.path
        for changed in summarize_patch(instance.test_patch).files
    ]
    spec_paths = sorted(
        set(test_patch_paths).union(
            node_id.split("::", 1)[0]
            for node_id in instance.fail_to_pass
        ),
    )
    return stored.model_copy(
        update={
            "target": targets,
            "target_map": target_map,
            "spec_paths": spec_paths,
            "scope": scope,
        },
    )


def _patch_receipt(
    agent_receipts: Sequence[Receipt],
    patch_text: str,
    after_seq: int,
    protected_modules: frozenset[str],
) -> Receipt:
    candidates = [
        receipt
        for receipt in agent_receipts
        if receipt.seq > after_seq
        and receipt.kind == "diff"
        and receipt.diff is not None
    ]
    if not candidates:
        raise ValueError(
            f"stored agent receipts have no diff receipt after sequence {after_seq}",
        )
    stored = min(candidates, key=lambda receipt: receipt.seq)
    return stored.model_copy(
        update={
            "diff": summarize_patch(
                patch_text,
                protected_modules,
            ),
        },
    )


def _synthetic_load_confirmation(
    *,
    attempt: int,
    origin: str,
    filtered_sha256: str,
    verification: Receipt,
) -> tuple[Receipt, Receipt]:
    branch_id = f"replay-confirm-{attempt}"
    applied_image = f"{origin}#replay-confirm-{attempt}-apply"
    apply = Receipt(
        receipt_id=f"{branch_id}-1",
        seq=1,
        branch_id=branch_id,
        kind="apply",
        exit_code=0,
        started_at=verification.started_at,
        duration_s=0,
        image_before=origin,
        image_after=applied_image,
        patch_sha256=filtered_sha256,
    )
    confirmation = Receipt(
        receipt_id=f"{branch_id}-2",
        seq=2,
        branch_id=branch_id,
        kind="verification",
        exit_code=verification.exit_code,
        stdout_tail=verification.stdout_tail,
        stderr_tail=verification.stderr_tail,
        started_at=verification.started_at,
        duration_s=verification.duration_s,
        image_before=applied_image,
        image_after=f"{origin}#replay-confirm-{attempt}-verified",
        junit=verification.junit,
    )
    return apply, confirmation


def _stored_v1_verdict(
    attempt_dir: Path,
    record_attempt: AttemptRecord,
) -> Verdict:
    verdict = Verdict.model_validate_json(
        (attempt_dir / "verdict.json").read_text(encoding="utf-8"),
    )
    if verdict.status != record_attempt.gate_status:
        raise ValueError(
            f"{attempt_dir}: verdict status {verdict.status} does not match "
            f"record status {record_attempt.gate_status}",
        )
    failed = verdict.failed_predicate_ids()
    if failed != record_attempt.failed_predicate_ids:
        raise ValueError(
            f"{attempt_dir}: verdict predicates {failed} do not match "
            f"record predicates {record_attempt.failed_predicate_ids}",
        )
    return verdict


def _replay_attempt(
    *,
    record_set: str,
    instance: Instance,
    record_attempt: AttemptRecord,
    result: RunResult,
    result_attempt: AttemptResult,
    stored_baseline: Baseline,
    run_dir: Path,
    agent_receipts: Sequence[Receipt],
    after_seq: int,
    scope: PatchScope,
    protected_modules: frozenset[str],
) -> tuple[ReplayAttempt, int]:
    attempt_dir = run_dir / "attempts" / str(result_attempt.number)
    patch_text = (attempt_dir / "patch.diff").read_text(encoding="utf-8")
    filtered_text = (attempt_dir / "filtered.diff").read_text(encoding="utf-8")
    filtered_sha256 = _sha256(filtered_text)
    patch = _patch_receipt(
        agent_receipts,
        patch_text,
        after_seq,
        protected_modules,
    )
    preceding_receipts = [
        receipt
        for receipt in agent_receipts
        if receipt.seq < patch.seq
    ]

    witness_receipts = _read_receipts(attempt_dir / "witness" / "receipts.jsonl")
    apply = next(
        (receipt for receipt in witness_receipts if receipt.kind == "apply"),
        None,
    )
    verification = next(
        (receipt for receipt in witness_receipts if receipt.kind == "verification"),
        None,
    )
    if apply is None or verification is None:
        raise ValueError(f"{attempt_dir}: witness apply or verification is missing")
    reruns = [
        receipt
        for receipt in witness_receipts
        if receipt.kind == "verification" and receipt.receipt_id != verification.receipt_id
    ]

    load_failure = None
    confirmation_apply = None
    confirmation = None
    if (
        not verification.timed_out
        and verification.exit_code in (2, 3, 4)
    ):
        load_failure = "assumed reproduced"
        confirmation_apply, confirmation = _synthetic_load_confirmation(
            attempt=result_attempt.number,
            origin=result.checkpoint_id,
            filtered_sha256=filtered_sha256,
            verification=verification,
        )

    baseline = _v2_baseline(stored_baseline, instance, scope)
    v2_verdict = evaluate(
        branch_id=result.agent_branch_id,
        witness_id=result_attempt.witness_branch_id,
        baseline=baseline,
        origin=result.checkpoint_id,
        receipts=preceding_receipts,
        patch=patch,
        apply=apply,
        verification=verification,
        filtered_sha256=filtered_sha256,
        claims=result_attempt.worker.claims,
        reruns=reruns,
        load_confirmation_apply=confirmation_apply,
        load_confirmation=confirmation,
    )
    v1_verdict = _stored_v1_verdict(attempt_dir, record_attempt)
    row = ReplayAttempt(
        record_set=record_set,
        instance_id=instance.instance_id,
        attempt=result_attempt.number,
        v1_status=v1_verdict.status,
        v1_failed_predicate_ids=v1_verdict.failed_predicate_ids(),
        v2_status=v2_verdict.status,
        v2_failed_predicate_ids=v2_verdict.failed_predicate_ids(),
        official_resolved=record_attempt.official_resolved,
        status_changed=v1_verdict.status != v2_verdict.status,
        load_failure=load_failure,
    )
    return row, patch.seq


def _counts(attempts: Iterable[ReplayAttempt], field: str) -> dict[str, int]:
    counts = {status: 0 for status in _STATUSES}
    for attempt in attempts:
        counts[getattr(attempt, field)] += 1
    return counts


def _summary(attempts: list[ReplayAttempt]) -> ReplaySummary:
    unresolved_passes = [
        attempt
        for attempt in attempts
        if attempt.v2_status == "PASS" and attempt.official_resolved is not True
    ]
    return ReplaySummary(
        v1_status_counts=_counts(attempts, "v1_status"),
        v2_status_counts=_counts(attempts, "v2_status"),
        became_pass=[
            attempt
            for attempt in attempts
            if attempt.v1_status != "PASS" and attempt.v2_status == "PASS"
        ],
        became_rejected=[
            attempt
            for attempt in attempts
            if attempt.v1_status != "REJECTED"
            and attempt.v2_status == "REJECTED"
        ],
        stopped_being_error=[
            attempt
            for attempt in attempts
            if attempt.v1_status == "ERROR" and attempt.v2_status != "ERROR"
        ],
        new_gate_looser=[
            attempt
            for attempt in unresolved_passes
            if attempt.v1_status != "PASS"
        ],
        pre_existing_unresolved_pass=[
            attempt
            for attempt in unresolved_passes
            if attempt.v1_status == "PASS"
        ],
    )


def build_replay(
    run_dirs: Sequence[Path],
    data_path: Path,
) -> ReplayReport:
    selected = [
        (
            record_set,
            path,
            InstanceRecord.model_validate_json(path.read_text(encoding="utf-8")),
        )
        for record_set, path in _record_paths(run_dirs)
    ]
    wanted = {
        record.instance_id
        for _, _, record in selected
        if record.attempts
    }
    instances = _load_instances(data_path, wanted)
    protected_modules = default_protected_modules()
    prepared = []
    scope_paths: dict[str, set[str]] = {}
    for record_set, record_path, record in selected:
        if not record.attempts:
            continue
        run_dir = _run_directory(record.run_dir, record_path)
        result = RunResult.model_validate_json(
            (run_dir / "result.json").read_text(encoding="utf-8"),
        )
        stored_baseline = Baseline.model_validate_json(
            (run_dir / "baseline.json").read_text(encoding="utf-8"),
        )
        if len(record.attempts) != len(result.attempts):
            raise ValueError(
                f"{record.instance_id}: record has {len(record.attempts)} attempts "
                f"but result has {len(result.attempts)}",
            )
        agent_receipts = _read_receipts(run_dir / "agent" / "receipts.jsonl")
        paths = scope_paths.setdefault(record.instance_id, set())
        paths.update(
            node_id.split("::", 1)[0]
            for node_id in stored_baseline.collected_ids
        )
        for result_attempt in result.attempts:
            patch_text = (
                run_dir
                / "attempts"
                / str(result_attempt.number)
                / "patch.diff"
            ).read_text(encoding="utf-8")
            paths.update(
                changed.path
                for changed in summarize_patch(
                    patch_text,
                    protected_modules,
                ).files
                if changed.status in ("modified", "deleted")
            )
        prepared.append(
            (
                record_set,
                record,
                run_dir,
                result,
                stored_baseline,
                agent_receipts,
            ),
        )

    scopes = {
        instance_id: _inferred_scope(paths, protected_modules)
        for instance_id, paths in scope_paths.items()
    }
    rows: list[ReplayAttempt] = []
    for (
        record_set,
        record,
        run_dir,
        result,
        stored_baseline,
        agent_receipts,
    ) in prepared:
        after_seq = 0
        for record_attempt, result_attempt in zip(
            record.attempts,
            result.attempts,
            strict=True,
        ):
            row, after_seq = _replay_attempt(
                record_set=record_set,
                instance=instances[record.instance_id],
                record_attempt=record_attempt,
                result=result,
                result_attempt=result_attempt,
                stored_baseline=stored_baseline,
                run_dir=run_dir,
                agent_receipts=agent_receipts,
                after_seq=after_seq,
                scope=scopes[record.instance_id],
                protected_modules=protected_modules,
            )
            rows.append(row)

    rows.sort(key=lambda row: (row.record_set, row.instance_id, row.attempt))
    return ReplayReport(attempts=rows, summary=_summary(rows))


def _official(value: bool | None) -> str:
    if value is True:
        return "RESOLVED"
    if value is False:
        return "NOT RESOLVED"
    return "UNAVAILABLE"


def _attempt_label(attempt: ReplayAttempt) -> str:
    return (
        f"{attempt.record_set}/{attempt.instance_id} attempt {attempt.attempt} "
        f"({_official(attempt.official_resolved)})"
    )


def _markdown_list(attempts: Sequence[ReplayAttempt]) -> str:
    if not attempts:
        return "- None"
    return "\n".join(f"- {_attempt_label(attempt)}" for attempt in attempts)


def summary_line(report: ReplayReport) -> str:
    changed = sum(attempt.status_changed for attempt in report.attempts)
    blockers = len(report.summary.new_gate_looser)
    return (
        f"REPLAY attempts={len(report.attempts)} changed={changed} "
        f"new_gate_looser={blockers} blocker={'yes' if blockers else 'no'}"
    )


def render(report: ReplayReport) -> str:
    blockers = len(report.summary.new_gate_looser)
    first_line = (
        f"# BLOCKER: {blockers} NEW gate-looser "
        f"{'attempt' if blockers == 1 else 'attempts'}"
        if blockers
        else "# CLEAR: no NEW gate-looser attempts"
    )
    lines = [
        first_line,
        "",
        "## Method notes",
        "",
        (
            "Every attempt's scope is inferred because v1 did not store the "
            "checkpoint's tree. Modified and deleted patch paths plus collected "
            "test files supply the partial C0 inventory."
        ),
        (
            "B2 confirmations are assumed for stored witness exits 2, 3 and 4: "
            "the original exit code and evidence are treated as reproduced on a "
            "second clean witness."
        ),
        "",
        "## Status counts",
        "",
        "| Gate | PASS | REJECTED | ERROR |",
        "| --- | ---: | ---: | ---: |",
        (
            "| v1 | "
            f"{report.summary.v1_status_counts['PASS']} | "
            f"{report.summary.v1_status_counts['REJECTED']} | "
            f"{report.summary.v1_status_counts['ERROR']} |"
        ),
        (
            "| v2 replay | "
            f"{report.summary.v2_status_counts['PASS']} | "
            f"{report.summary.v2_status_counts['REJECTED']} | "
            f"{report.summary.v2_status_counts['ERROR']} |"
        ),
        "",
        "## Attempt table",
        "",
        (
            "| Record set | Instance | Attempt | v1 | v1 failed | v2 | "
            "v2 failed | Official | Changed | Scope | Load failure |"
        ),
        "| --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for attempt in report.attempts:
        lines.append(
            "| "
            + " | ".join(
                (
                    attempt.record_set,
                    attempt.instance_id,
                    str(attempt.attempt),
                    attempt.v1_status,
                    ", ".join(attempt.v1_failed_predicate_ids) or "none",
                    attempt.v2_status,
                    ", ".join(attempt.v2_failed_predicate_ids) or "none",
                    _official(attempt.official_resolved),
                    "yes" if attempt.status_changed else "no",
                    attempt.scope,
                    attempt.load_failure or "none",
                ),
            )
            + " |",
        )
    lines.extend(
        [
            "",
            "## Became PASS",
            "",
            _markdown_list(report.summary.became_pass),
            "",
            "## Became REJECTED",
            "",
            _markdown_list(report.summary.became_rejected),
            "",
            "## Stopped being ERROR",
            "",
            _markdown_list(report.summary.stopped_being_error),
            "",
            "## Unresolved v2 PASS: NEW",
            "",
            _markdown_list(report.summary.new_gate_looser),
            "",
            "## Unresolved v2 PASS: PRE-EXISTING",
            "",
            _markdown_list(report.summary.pre_existing_unresolved_pass),
            "",
            summary_line(report),
            "",
        ],
    )
    return "\n".join(lines)


def write_replay(
    run_dirs: Sequence[Path],
    data_path: Path,
    out_prefix: Path,
) -> ReplayReport:
    report = build_replay(run_dirs, data_path)
    json_path = Path(f"{out_prefix}.json")
    markdown_path = Path(f"{out_prefix}.md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render(report), encoding="utf-8")
    return report


__all__ = [
    "ReplayAttempt",
    "ReplayReport",
    "ReplaySummary",
    "build_replay",
    "render",
    "summary_line",
    "write_replay",
]
