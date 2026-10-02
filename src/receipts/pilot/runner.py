"""Run and resume the pre-registered SWE-rebench pilot."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import shutil
import time
import traceback
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

from receipts.agent.worker import WorkerOutcome
from receipts.cost import estimate_daytona_sandbox_dollars
from receipts.llm import ModelClient
from receipts.models import ClaimAudit, Claims, Receipt, VerdictStatus
from receipts.orchestrate import RunBudgets, RunResult, fix
from receipts.pilot.grade import OfficialRecord, grade_attempts
from receipts.sandbox.protocol import Executor
from receipts.sandbox.sink import RunSink
from receipts.swerebench import Agreement, Instance, UnparseableTestPatch, agreement, to_task
from receipts.verify.run import BaselineBroken, BaselineTooSlow, TargetNotFailing


PilotStatus = Literal["ran", "excluded", "infra_error"]


class AttemptRecord(BaseModel):
    end: Literal[
        "finished",
        "budget_exhausted",
        "protocol_error",
        "model_error",
    ]
    claimed_done: bool
    claims: Claims | None
    naive_green: bool
    gate_status: VerdictStatus
    failed_predicate_ids: list[str]
    claim_audit: ClaimAudit
    official_resolved: bool | None
    agreement: Agreement | None
    filtered_patch_sha256: str
    filtered_sha256: str | None = None
    witness_apply_sha256: str | None = None
    gate_error: str | None = None
    official: OfficialRecord | None = None


class FinalRecord(BaseModel):
    gate_status: VerdictStatus
    verified_fix: bool
    official_resolved: bool | None


class PilotCost(BaseModel):
    tokens: int = Field(ge=0)
    model_dollars: float | None = Field(
        default=None,
        validation_alias=AliasChoices("model_dollars", "dollars"),
    )
    sandbox_lifetime_seconds: float = Field(default=0, ge=0)
    sandbox_dollars_estimate: float = Field(default=0, ge=0)


class PriorInfrastructureError(BaseModel):
    reason: str
    run_dir: str


class InstanceRecord(BaseModel):
    instance_id: str
    status: PilotStatus
    reason: str | None
    run_dir: str
    attempts: list[AttemptRecord]
    final: FinalRecord | None
    cost: PilotCost
    wall_time_s: float = Field(ge=0)
    prior_infrastructure_errors: list[PriorInfrastructureError] = Field(
        default_factory=list,
    )


ExecutorFactory = Callable[[str], Executor]
_PREREGISTERED_BASELINE_LIMIT_S = 300
_MAX_INFRASTRUCTURE_RUNS = 3


class _BaselineGuard:
    def __init__(self, run_pytest: Any, limit_s: int) -> None:
        self.run_pytest = run_pytest
        self.limit_s = limit_s
        self.baseline_runs = 0

    async def __call__(self, *args: Any, **kwargs: Any) -> Receipt:
        receipt = await self.run_pytest(*args, **kwargs)
        if self.baseline_runs < 2:
            self.baseline_runs += 1
            if receipt.duration_s >= self.limit_s:
                raise BaselineTooSlow(receipt.duration_s)
        return receipt


class _DurablePilotSink:
    def __init__(self, original: Any, run_dir: Path) -> None:
        self.original = original
        original_run_dir = getattr(original, "run_dir", None)
        if original_run_dir is not None and Path(original_run_dir) == run_dir:
            self.durable = original
            self._write_original = False
        else:
            self.durable = RunSink(run_dir)
            self._write_original = True
        self._run_dir = run_dir

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.") or "receipt"

    def _preserve_log(self, receipt: Receipt) -> None:
        if receipt.log_path is None:
            return
        source = Path(receipt.log_path)
        if not source.is_file():
            return
        target = (
            self._run_dir
            / "logs"
            / self._safe_name(receipt.branch_id)
            / f"{self._safe_name(receipt.receipt_id)}.log"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        receipt.log_path = str(target)

    def _preserve_patch(self, receipt: Receipt) -> None:
        if receipt.diff is None or receipt.diff.patch_path is None:
            return
        source = Path(receipt.diff.patch_path)
        if not source.is_file():
            return
        target = (
            self._run_dir
            / "artifacts"
            / self._safe_name(receipt.branch_id)
            / f"{self._safe_name(receipt.receipt_id)}.patch"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        receipt.diff.patch_path = str(target)

    def write(self, receipt: Receipt) -> None:
        self._preserve_log(receipt)
        self._preserve_patch(receipt)
        if self._write_original:
            self.original.write(receipt)
        self.durable.write(receipt)


def _run_id(instance_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", instance_id).strip("-.")
    prefix = safe_id[:48] or "instance"
    return f"pilot-{prefix}-{uuid.uuid4().hex[:10]}"


def _pilot_cost(
    result: RunResult | None,
    sandbox_usage: Sequence[dict[str, Any]],
) -> PilotCost:
    tokens = 0
    models = result.cost.get("models") if result is not None else None
    if isinstance(models, dict):
        for values in models.values():
            if not isinstance(values, dict):
                continue
            for name in ("prompt_tokens", "completion_tokens", "reasoning_tokens"):
                value = values.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    tokens += value

    dollars = result.cost.get("estimated_dollars") if result is not None else None
    if not isinstance(dollars, (int, float)) or isinstance(dollars, bool):
        dollars = None
    sandbox_lifetime_seconds = sum(
        float(item["seconds"])
        for item in sandbox_usage
    )
    return PilotCost(
        tokens=tokens,
        model_dollars=float(dollars) if dollars is not None else None,
        sandbox_lifetime_seconds=sandbox_lifetime_seconds,
        sandbox_dollars_estimate=estimate_daytona_sandbox_dollars(sandbox_usage),
    )


def _sandbox_usage(executor: Any) -> list[dict[str, Any]]:
    usage = getattr(executor, "sandbox_usage", None)
    if usage is None:
        return []
    return list(usage())


def _agent_receipts(run_dir: Path) -> list[Receipt]:
    path = run_dir / "agent" / "receipts.jsonl"
    if not path.is_file():
        return []
    return [
        Receipt.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _naive_green(worker: WorkerOutcome, receipts: Sequence[Receipt]) -> bool:
    worker_ids = set(worker.receipt_ids)
    pytest_receipts = [
        receipt
        for receipt in receipts
        if receipt.receipt_id in worker_ids
        and (
            receipt.junit is not None
            or (receipt.cmd is not None and "--junitxml=" in receipt.cmd)
        )
    ]
    if not pytest_receipts:
        return False
    last = pytest_receipts[-1]
    return bool(
        last.exit_code == 0
        and not last.timed_out
        and last.junit is not None
        and not last.junit.failed
        and not last.junit.errors
        and not last.junit.collection_errors
    )


def _claimed_done(worker: WorkerOutcome) -> bool:
    claims = worker.claims
    return bool(
        claims is not None
        and (claims.target_tests_pass or claims.full_suite_pass)
    )


def _filtered_patch_sha256(run_dir: Path, relative_path: str) -> str:
    return hashlib.sha256((run_dir / relative_path).read_bytes()).hexdigest()


def _ran_record(
    instance: Instance,
    run_dir: Path,
    result: RunResult,
    official_records: Sequence[OfficialRecord],
    wall_time_s: float,
    sandbox_usage: Sequence[dict[str, Any]],
) -> InstanceRecord:
    official_by_attempt = {record.attempt: record for record in official_records}
    receipts = _agent_receipts(run_dir)
    attempts: list[AttemptRecord] = []
    grading_errors: list[str] = []
    for attempt in result.attempts:
        try:
            official = official_by_attempt[attempt.number]
        except KeyError as exc:
            raise RuntimeError(
                f"official grading omitted attempt {attempt.number}",
            ) from exc
        if official.infra_error is None:
            official_resolved: bool | None = official.judgement.resolved
            attempt_agreement: Agreement | None = agreement(
                attempt.verdict,
                official.judgement,
            )
        else:
            official_resolved = None
            attempt_agreement = None
            grading_errors.append(
                f"attempt {attempt.number}: {official.infra_error}",
            )
        attempts.append(
            AttemptRecord(
                end=attempt.worker.end,
                claimed_done=_claimed_done(attempt.worker),
                claims=attempt.worker.claims,
                naive_green=_naive_green(attempt.worker, receipts),
                gate_status=attempt.verdict.status,
                failed_predicate_ids=attempt.verdict.failed_predicate_ids(),
                claim_audit=attempt.verdict.claim_audit,
                official_resolved=official_resolved,
                agreement=attempt_agreement,
                filtered_patch_sha256=_filtered_patch_sha256(
                    run_dir,
                    attempt.filtered_patch_path,
                ),
                filtered_sha256=attempt.filtered_sha256,
                witness_apply_sha256=attempt.witness_apply_sha256,
                gate_error=attempt.verdict.error,
                official=official,
            ),
        )

    if not attempts:
        raise RuntimeError("orchestration returned no attempts")
    final_attempt = attempts[-1]
    infrastructure_reason = None
    if grading_errors:
        infrastructure_reason = "official grading failed: " + "; ".join(
            grading_errors,
        )
    return InstanceRecord(
        instance_id=instance.instance_id,
        status="infra_error" if grading_errors else "ran",
        reason=infrastructure_reason,
        run_dir=str(run_dir),
        attempts=attempts,
        final=FinalRecord(
            gate_status=result.final_verdict.status,
            verified_fix=(
                result.verified_fix
                and final_attempt.official_resolved is True
            ),
            official_resolved=final_attempt.official_resolved,
        ),
        cost=_pilot_cost(result, sandbox_usage),
        wall_time_s=wall_time_s,
    )


async def _close_executor(executor: Any) -> None:
    close = getattr(executor, "close", None)
    if close is None:
        return
    closed = close()
    if inspect.isawaitable(closed):
        await closed


def _atomic_write_record(path: Path, record: InstanceRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_official_records(
    run_dir: Path,
    records: Sequence[OfficialRecord],
) -> None:
    path = run_dir / "official" / "records.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [record.model_dump(mode="json") for record in records],
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


async def run_instance(
    make_executor: ExecutorFactory,
    model: ModelClient,
    instance: Instance,
    pilot_dir: Path,
    budgets: RunBudgets,
) -> InstanceRecord:
    """Run, independently grade, and atomically record one pilot instance."""

    started = time.monotonic()
    instance_dir = pilot_dir / instance.instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    run_id = _run_id(instance.instance_id)
    run_dir = instance_dir / "runs" / run_id
    executor: Executor | None = None
    original_sink: Any = None
    sink_replaced = False
    original_run_pytest: Any = None
    pytest_replaced = False
    result: RunResult | None = None
    sandbox_usage: list[dict[str, Any]] = []

    try:
        try:
            executor = make_executor(run_id)
            original_sink = getattr(executor, "sink", None)
            if original_sink is not None:
                setattr(executor, "sink", _DurablePilotSink(original_sink, run_dir))
                sink_replaced = True
            original_run_pytest = getattr(executor, "run_pytest", None)
            baseline_limit_s = min(
                budgets.baseline_limit_s,
                _PREREGISTERED_BASELINE_LIMIT_S,
            )
            orchestration_budgets = budgets.model_copy(
                update={"baseline_limit_s": baseline_limit_s * 2},
            )
            if original_run_pytest is not None:
                setattr(
                    executor,
                    "run_pytest",
                    _BaselineGuard(original_run_pytest, baseline_limit_s),
                )
                pytest_replaced = True
            task = to_task(instance)
            result = await fix(
                executor,
                model,
                task.source,
                task.issue,
                task.spec_tests,
                task.suite_scope,
                run_dir,
                appeals=1,
                budgets=orchestration_budgets,
                spec_paths=task.spec_paths,
            )
            official_records = await grade_attempts(
                executor,
                result,
                run_dir,
                instance,
                timeout_s=budgets.verification_timeout_s,
            )
            _write_official_records(run_dir, official_records)
        finally:
            try:
                if executor is not None:
                    await _close_executor(executor)
            finally:
                if executor is not None:
                    sandbox_usage = _sandbox_usage(executor)
                if executor is not None and sink_replaced:
                    setattr(executor, "sink", original_sink)
                if executor is not None and pytest_replaced:
                    setattr(executor, "run_pytest", original_run_pytest)
        record = _ran_record(
            instance,
            run_dir,
            result,
            official_records,
            time.monotonic() - started,
            sandbox_usage,
        )
    except (BaselineBroken, BaselineTooSlow, TargetNotFailing, UnparseableTestPatch) as exc:
        record = InstanceRecord(
            instance_id=instance.instance_id,
            status="excluded",
            reason=str(exc),
            run_dir=str(run_dir),
            attempts=[],
            final=None,
            cost=_pilot_cost(result, sandbox_usage),
            wall_time_s=time.monotonic() - started,
        )
    except Exception as exc:
        error = traceback.format_exc()
        (instance_dir / "error.txt").write_text(error, encoding="utf-8")
        record = InstanceRecord(
            instance_id=instance.instance_id,
            status="infra_error",
            reason=f"{type(exc).__name__}: {exc}",
            run_dir=str(run_dir),
            attempts=[],
            final=None,
            cost=_pilot_cost(result, sandbox_usage),
            wall_time_s=time.monotonic() - started,
        )

    if record.status == "infra_error" and record.reason is not None:
        error_path = instance_dir / "error.txt"
        if not error_path.exists():
            error_path.write_text(record.reason + "\n", encoding="utf-8")
    _atomic_write_record(instance_dir / "record.json", record)
    return record


def _read_record(path: Path) -> InstanceRecord:
    return InstanceRecord.model_validate_json(path.read_text(encoding="utf-8"))


def _archived_infrastructure_errors(
    instance_dir: Path,
) -> list[PriorInfrastructureError]:
    errors: list[PriorInfrastructureError] = []
    for path in sorted(instance_dir.glob("record.infra-*.json")):
        record = _read_record(path)
        errors.append(
            PriorInfrastructureError(
                reason=record.reason or "reason unavailable",
                run_dir=record.run_dir,
            ),
        )
    return errors


def _archive_infrastructure_record(
    record_path: Path,
    record: InstanceRecord,
    prior_errors: Sequence[PriorInfrastructureError],
) -> list[PriorInfrastructureError]:
    archive_number = len(prior_errors) + 1
    archive_path = record_path.with_name(f"record.infra-{archive_number}.json")
    record_path.replace(archive_path)
    return [
        *prior_errors,
        PriorInfrastructureError(
            reason=record.reason or "reason unavailable",
            run_dir=record.run_dir,
        ),
    ]


def _append_progress(pilot_dir: Path, record: InstanceRecord) -> None:
    pilot_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "instance_id": record.instance_id,
        "status": record.status,
        "reason": record.reason,
        "record_path": f"{record.instance_id}/record.json",
    }
    with (pilot_dir / "progress.log").open("a", encoding="utf-8") as writer:
        writer.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
        writer.flush()


def _progress_ids(pilot_dir: Path) -> set[str]:
    path = pilot_dir / "progress.log"
    if not path.is_file():
        return set()
    instance_ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("instance_id"), str):
            instance_ids.add(value["instance_id"])
    return instance_ids


async def run_pilot(
    make_executor: ExecutorFactory,
    model: ModelClient,
    candidates: Sequence[Instance],
    pilot_dir: Path,
    n: int,
    concurrency: int = 1,
    budgets: RunBudgets | None = None,
) -> list[InstanceRecord]:
    """Walk candidates in order until exactly ``n`` completed runs exist."""

    if n < 0:
        raise ValueError("n must be non-negative")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    budget = budgets or RunBudgets()
    records: list[InstanceRecord] = []
    progress_ids = _progress_ids(pilot_dir)
    ran = 0
    index = 0

    async def run_and_log(instance: Instance) -> InstanceRecord:
        instance_dir = pilot_dir / instance.instance_id
        record_path = instance_dir / "record.json"
        prior_errors = _archived_infrastructure_errors(instance_dir)
        record = _read_record(record_path) if record_path.is_file() else None

        if (
            record is not None
            and record.status != "infra_error"
            and record.prior_infrastructure_errors != prior_errors
        ):
            record.prior_infrastructure_errors = list(prior_errors)
            _atomic_write_record(record_path, record)

        while record is None or record.status == "infra_error":
            if record is not None:
                if len(prior_errors) + 1 >= _MAX_INFRASTRUCTURE_RUNS:
                    record.prior_infrastructure_errors = list(prior_errors)
                    _atomic_write_record(record_path, record)
                    break
                prior_errors = _archive_infrastructure_record(
                    record_path,
                    record,
                    prior_errors,
                )
            record = await run_instance(
                make_executor,
                model,
                instance,
                pilot_dir,
                budget,
            )
            record.prior_infrastructure_errors = list(prior_errors)
            _atomic_write_record(record_path, record)

        if record.instance_id not in progress_ids:
            _append_progress(pilot_dir, record)
            progress_ids.add(record.instance_id)
        return record

    while index < len(candidates) and ran < n:
        batch: list[Instance] = []
        while (
            index < len(candidates)
            and ran < n
            and len(batch) < min(concurrency, n - ran)
        ):
            instance = candidates[index]
            index += 1
            batch.append(instance)

        if not batch:
            continue
        completed = await asyncio.gather(
            *(run_and_log(instance) for instance in batch),
        )
        for record in completed:
            records.append(record)
            if record.status == "ran":
                ran += 1

    return records


__all__ = [
    "AttemptRecord",
    "FinalRecord",
    "InstanceRecord",
    "PilotCost",
    "PriorInfrastructureError",
    "run_instance",
    "run_pilot",
]
