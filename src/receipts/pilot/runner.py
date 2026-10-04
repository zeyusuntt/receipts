"""Run and resume the pre-registered SWE-rebench pilot.

Rows in ``progress.jsonl`` are appended in completion order. Each row carries
the candidate's 1-based position so the original candidate order can be
reconstructed independently of concurrent completion order.
"""

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

from receipts.agent.worker import WorkerOutcome
from receipts.cost import (
    CostMeter,
    TokenUsage,
    estimate_daytona_sandbox_dollars,
    estimate_tokenfactory_sandbox_dollars,
)
from receipts.llm import ModelClient
from receipts.models import ClaimAudit, Claims, Receipt, VerdictStatus
from receipts.orchestrate import RunBudgets, RunResult, fix
from receipts.pilot.grade import OfficialRecord, grade_attempts
from receipts.sandbox.protocol import Executor
from receipts.sandbox.sink import RunSink
from receipts.swerebench import Agreement, Instance, UnparseableTestPatch, agreement, to_task
from receipts.verify.run import BaselineBroken, BaselineTooSlow, TargetNotFailing


PilotStatus = Literal["ran", "excluded", "infra_error", "interrupted"]
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AttemptRecord(BaseModel):
    end: Literal[
        "finished",
        "budget_exhausted",
        "protocol_error",
        "model_error",
    ]
    end_summary: str | None = None
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


class PriorInterruptedRun(BaseModel):
    reason: str
    run_dir: str
    cost: PilotCost
    wall_time_s: float = Field(ge=0)


class InstanceRecord(BaseModel):
    instance_id: str
    status: PilotStatus
    reason: str | None
    run_dir: str
    executor_kind: str | None = None
    attempts: list[AttemptRecord]
    final: FinalRecord | None
    cost: PilotCost
    wall_time_s: float = Field(ge=0)
    cleanup_error: str | None = None
    prior_infrastructure_errors: list[PriorInfrastructureError] = Field(
        default_factory=list,
    )
    prior_interrupted_runs: list[PriorInterruptedRun] = Field(
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
                limit_s = (
                    kwargs.get("timeout_s", self.limit_s) if receipt.timed_out
                    else self.limit_s
                )
                raise BaselineTooSlow(
                    receipt.duration_s, limit_s=limit_s, timed_out=receipt.timed_out,
                )
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


def _executor_kind_from_instance(executor: Any) -> str:
    name = type(executor).__name__
    if name.endswith("Executor"):
        name = name[: -len("Executor")]
    return name.lower()


def _pilot_cost(
    result: Any | None,
    sandbox_usage: Sequence[dict[str, Any]],
) -> PilotCost:
    tokens = 0
    if isinstance(result, dict):
        cost = result
        disclosure = None
    else:
        cost = getattr(result, "cost", {}) if result is not None else {}
        disclosure = getattr(result, "disclosure", None)
    models = cost.get("models") if isinstance(cost, dict) else None
    if isinstance(models, dict):
        for values in models.values():
            if not isinstance(values, dict):
                continue
            for name in ("prompt_tokens", "completion_tokens", "reasoning_tokens"):
                value = values.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    tokens += value

    dollars = cost.get("estimated_dollars") if isinstance(cost, dict) else None
    if not isinstance(dollars, (int, float)) or isinstance(dollars, bool):
        dollars = None
    sandbox_lifetime_seconds = sum(
        float(item["seconds"])
        for item in sandbox_usage
    )
    executor_kind = getattr(disclosure, "executor_kind", None)
    tokenfactory_usage: list[dict[str, Any]] = []
    daytona_usage: list[dict[str, Any]] = []
    for item in sandbox_usage:
        item_kind = re.sub(
            r"[^a-z0-9]+",
            "",
            str(item.get("executor_kind", "")).lower(),
        )
        resources = item.get("resources")
        zero_resources = False
        if isinstance(resources, dict):
            try:
                zero_resources = all(
                    float(resources[name]) == 0
                    for name in ("cpu", "memory", "disk")
                )
            except (KeyError, TypeError, ValueError):
                zero_resources = False
        reported = (
            executor_kind == "tokenfactory"
            or item_kind == "tokenfactory"
            or ("cost" in item and zero_resources)
        )
        if reported:
            tokenfactory_usage.append(item)
        else:
            daytona_usage.append(item)
    sandbox_dollars = estimate_daytona_sandbox_dollars(daytona_usage)
    sandbox_dollars += estimate_tokenfactory_sandbox_dollars(tokenfactory_usage)
    return PilotCost(
        tokens=tokens,
        model_dollars=float(dollars) if dollars is not None else None,
        sandbox_lifetime_seconds=sandbox_lifetime_seconds,
        sandbox_dollars_estimate=sandbox_dollars,
    )


def _partial_pilot_cost(
    run_dir: Path,
    result: RunResult | None,
    sandbox_usage: Sequence[dict[str, Any]],
) -> PilotCost:
    if result is not None:
        return _pilot_cost(result, sandbox_usage)
    result_path = run_dir / "result.json"
    if result_path.is_file():
        try:
            stored_result = RunResult.model_validate_json(
                result_path.read_text(encoding="utf-8"),
            )
        except (OSError, ValueError):
            pass
        else:
            return _pilot_cost(stored_result, sandbox_usage)
    cost_path = run_dir / "cost.json"
    if cost_path.is_file():
        try:
            stored_cost = json.loads(cost_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        else:
            if isinstance(stored_cost, dict):
                return _pilot_cost(stored_cost, sandbox_usage)
    partial_model_cost = _partial_model_cost(run_dir)
    if partial_model_cost is not None:
        return _pilot_cost(partial_model_cost, sandbox_usage)
    return _pilot_cost(None, sandbox_usage)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _partial_model_cost(run_dir: Path) -> dict[str, Any] | None:
    disclosure = _read_json_object(run_dir / "disclosure.json")
    model_values = disclosure.get("model") if disclosure is not None else None
    if not isinstance(model_values, dict):
        return None
    model_name = model_values.get("model") or model_values.get("client")
    if not isinstance(model_name, str) or not model_name:
        return None

    meter = CostMeter()
    usage_found = False
    plan = _read_json_object(run_dir / "plan.json")
    if plan is not None and isinstance(plan.get("usage"), dict):
        try:
            meter.add_usage(model_name, TokenUsage.model_validate(plan["usage"]))
        except ValueError:
            pass
        else:
            usage_found = True

    worker_log = run_dir / "agent" / "worker.jsonl"
    try:
        worker_lines = worker_log.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        worker_lines = []
    for line in worker_lines:
        try:
            row = json.loads(line)
            usage = row.get("usage") if isinstance(row, dict) else None
            parsed = TokenUsage.model_validate(usage)
        except (json.JSONDecodeError, ValueError):
            continue
        meter.add_usage(model_name, parsed)
        usage_found = True
    return meter.summary() if usage_found else None


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


def _record_run_dir(run_dir: str | Path) -> str:
    path = Path(run_dir).resolve()
    try:
        return path.relative_to(_REPOSITORY_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _stored_run_dir(run_dir: str | Path) -> str:
    path = Path(run_dir)
    if not path.is_absolute():
        return path.as_posix()
    return _record_run_dir(path)


def _normalize_record_paths(record: InstanceRecord) -> InstanceRecord:
    record.run_dir = _stored_run_dir(record.run_dir)
    record.prior_infrastructure_errors = [
        prior.model_copy(update={"run_dir": _stored_run_dir(prior.run_dir)})
        for prior in record.prior_infrastructure_errors
    ]
    record.prior_interrupted_runs = [
        prior.model_copy(update={"run_dir": _stored_run_dir(prior.run_dir)})
        for prior in record.prior_interrupted_runs
    ]
    return record


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
                end_summary=attempt.worker.summary,
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
    gate_infrastructure_error = next(
        (
            attempt.verdict.error
            for attempt in result.attempts
            if attempt.verdict.error_kind == "infrastructure"
        ),
        None,
    )
    infrastructure_reason = gate_infrastructure_error
    if infrastructure_reason is None and grading_errors:
        infrastructure_reason = "official grading failed: " + "; ".join(
            grading_errors,
        )
    return InstanceRecord(
        instance_id=instance.instance_id,
        status="infra_error" if infrastructure_reason is not None else "ran",
        reason=infrastructure_reason,
        run_dir=_record_run_dir(run_dir),
        executor_kind=getattr(
            getattr(result, "disclosure", None),
            "executor_kind",
            None,
        ),
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


async def _complete_shielded(
    awaitable: Any,
) -> tuple[Any, bool, BaseException | None]:
    """Finish an awaitable and retain cancellation plus any cleanup error."""

    task = asyncio.ensure_future(awaitable)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            pass
    try:
        return task.result(), cancelled, None
    except BaseException as exc:
        return None, cancelled, exc


async def _await_shielded(awaitable: Any) -> Any:
    """Finish cleanup despite caller cancellation, then propagate cancellation."""

    result, cancelled, error = await _complete_shielded(awaitable)
    if cancelled:
        raise asyncio.CancelledError
    if error is not None:
        raise error
    return result


def _shield_cleanup_methods(executor: Any) -> Any:
    """Protect an executor's async release and close operations from cancellation."""

    for name in ("release", "close"):
        original = getattr(executor, name, None)
        if original is None or getattr(original, "_receipts_shielded", False):
            continue

        async def shielded(*args: Any, _original: Any = original, **kwargs: Any) -> Any:
            result = _original(*args, **kwargs)
            if inspect.isawaitable(result):
                return await _await_shielded(result)
            return result

        setattr(shielded, "_receipts_shielded", True)
        setattr(executor, name, shielded)
    return executor


async def _cleanup_executor(
    executor: Any,
    *,
    original_sink: Any,
    sink_replaced: bool,
    original_run_pytest: Any,
    pytest_replaced: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    sandbox_usage: list[dict[str, Any]] = []
    cleanup_errors: list[str] = []
    try:
        if executor is not None:
            try:
                await _close_executor(executor)
            except Exception as exc:
                cleanup_errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        if executor is not None:
            try:
                sandbox_usage = _sandbox_usage(executor)
            except Exception as exc:
                cleanup_errors.append(
                    f"sandbox usage failed: {type(exc).__name__}: {exc}",
                )
        if executor is not None and sink_replaced:
            setattr(executor, "sink", original_sink)
        if executor is not None and pytest_replaced:
            setattr(executor, "run_pytest", original_run_pytest)
    return sandbox_usage, cleanup_errors


def baseline_guard(run_pytest: Any, limit_s: int) -> Any:
    """Expose the pilot's per-run baseline limit without changing its policy."""
    return _BaselineGuard(run_pytest, limit_s)


def shield_cleanup_methods(executor: Any) -> Any:
    """Expose the pilot's cancellation-safe executor lifecycle methods."""
    return _shield_cleanup_methods(executor)


async def complete_shielded(awaitable: Any) -> tuple[Any, bool, BaseException | None]:
    """Expose the pilot's cleanup completion and cancellation accounting."""
    return await _complete_shielded(awaitable)


def _atomic_write_record(path: Path, record: InstanceRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_final_infrastructure_error(
    instance_dir: Path,
    record: InstanceRecord,
    runs: int,
) -> None:
    path = instance_dir / "final_infra_error.json"
    if path.is_file():
        return
    payload = {
        "instance_id": record.instance_id,
        "runs": runs,
        "reason": record.reason or "reason unavailable",
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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
    executor_kind: str | None = None
    original_sink: Any = None
    sink_replaced = False
    original_run_pytest: Any = None
    pytest_replaced = False
    result: RunResult | None = None
    sandbox_usage: list[dict[str, Any]] = []
    cleanup_errors: list[str] = []

    try:
        try:
            executor = make_executor(run_id)
            executor_kind = _executor_kind_from_instance(executor)
            executor = _shield_cleanup_methods(executor)
            if hasattr(executor, "cleanup_manifest"):
                setattr(executor, "cleanup_manifest", run_dir / "cleanup.json")
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
            sandbox_usage, cleanup_errors = await _await_shielded(
                _cleanup_executor(
                    executor,
                    original_sink=original_sink,
                    sink_replaced=sink_replaced,
                    original_run_pytest=original_run_pytest,
                    pytest_replaced=pytest_replaced,
                ),
            )
        record = _ran_record(
            instance,
            run_dir,
            result,
            official_records,
            time.monotonic() - started,
            sandbox_usage,
        )
        if record.executor_kind is None:
            record.executor_kind = executor_kind
    except asyncio.CancelledError:
        if not sandbox_usage and executor is not None:
            try:
                sandbox_usage = _sandbox_usage(executor)
            except Exception as exc:
                cleanup_errors.append(
                    f"sandbox usage failed: {type(exc).__name__}: {exc}",
                )
        run_dir.mkdir(parents=True, exist_ok=True)
        record = InstanceRecord(
            instance_id=instance.instance_id,
            status="interrupted",
            reason="interrupted",
            run_dir=_record_run_dir(run_dir),
            executor_kind=executor_kind,
            attempts=[],
            final=None,
            cost=_partial_pilot_cost(run_dir, result, sandbox_usage),
            wall_time_s=time.monotonic() - started,
            cleanup_error="; ".join(cleanup_errors) if cleanup_errors else None,
        )
        _archive_interrupted_record(instance_dir, record)
        raise
    except (BaselineBroken, BaselineTooSlow, TargetNotFailing, UnparseableTestPatch) as exc:
        record = InstanceRecord(
            instance_id=instance.instance_id,
            status="excluded",
            reason=str(exc),
            run_dir=_record_run_dir(run_dir),
            executor_kind=executor_kind,
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
            run_dir=_record_run_dir(run_dir),
            executor_kind=executor_kind,
            attempts=[],
            final=None,
            cost=_pilot_cost(result, sandbox_usage),
            wall_time_s=time.monotonic() - started,
        )

    if cleanup_errors:
        record.cleanup_error = "; ".join(cleanup_errors)
    if record.status == "infra_error" and record.reason is not None:
        error_path = instance_dir / "error.txt"
        if not error_path.exists():
            error_path.write_text(record.reason + "\n", encoding="utf-8")
    _atomic_write_record(instance_dir / "record.json", record)
    return record


def _read_record(path: Path) -> InstanceRecord:
    return InstanceRecord.model_validate_json(path.read_text(encoding="utf-8"))


def _archive_interrupted_record(
    instance_dir: Path,
    record: InstanceRecord,
) -> Path:
    number = 1
    while True:
        archive_path = instance_dir / f"record.interrupted-{number}.json"
        if not archive_path.exists():
            break
        number += 1
    _normalize_record_paths(record)
    _atomic_write_record(archive_path, record)
    return archive_path


def _archived_infrastructure_errors(
    instance_dir: Path,
) -> list[PriorInfrastructureError]:
    errors: list[PriorInfrastructureError] = []
    for path in sorted(instance_dir.glob("record.infra-*.json")):
        record = _read_record(path)
        errors.append(
            PriorInfrastructureError(
                reason=record.reason or "reason unavailable",
                run_dir=_stored_run_dir(record.run_dir),
            ),
        )
    return errors


def _archived_interrupted_runs(
    instance_dir: Path,
) -> list[PriorInterruptedRun]:
    interrupted: list[PriorInterruptedRun] = []
    for path in sorted(instance_dir.glob("record.interrupted-*.json")):
        record = _read_record(path)
        interrupted.append(
            PriorInterruptedRun(
                reason=record.reason or "interrupted",
                run_dir=_stored_run_dir(record.run_dir),
                cost=record.cost,
                wall_time_s=record.wall_time_s,
            ),
        )
    return interrupted


def _archive_infrastructure_record(
    record_path: Path,
    record: InstanceRecord,
    prior_errors: Sequence[PriorInfrastructureError],
) -> list[PriorInfrastructureError]:
    archive_number = len(prior_errors) + 1
    archive_path = record_path.with_name(f"record.infra-{archive_number}.json")
    record = _normalize_record_paths(record.model_copy(deep=True))
    _atomic_write_record(record_path, record)
    record_path.replace(archive_path)
    return [
        *(
            prior.model_copy(update={"run_dir": _stored_run_dir(prior.run_dir)})
            for prior in prior_errors
        ),
        PriorInfrastructureError(
            reason=record.reason or "reason unavailable",
            run_dir=record.run_dir,
        ),
    ]


def _append_progress(
    pilot_dir: Path,
    record: InstanceRecord,
    candidate_position: int,
) -> None:
    pilot_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "candidate_position": candidate_position,
        "instance_id": record.instance_id,
        "status": record.status,
        "reason": record.reason,
        "record_path": f"{record.instance_id}/record.json",
    }
    with (pilot_dir / "progress.jsonl").open("a", encoding="utf-8") as writer:
        writer.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
        writer.flush()


def _progress_ids(pilot_dir: Path) -> set[str]:
    instance_ids: set[str] = set()
    for path in (pilot_dir / "progress.log", pilot_dir / "progress.jsonl"):
        if not path.is_file():
            continue
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

    async def run_and_log(
        candidate_position: int,
        instance: Instance,
    ) -> InstanceRecord:
        instance_dir = pilot_dir / instance.instance_id
        record_path = instance_dir / "record.json"
        prior_errors = _archived_infrastructure_errors(instance_dir)
        prior_interrupted = _archived_interrupted_runs(instance_dir)
        record = _read_record(record_path) if record_path.is_file() else None

        if (
            record is not None
            and record.status != "infra_error"
            and (
                record.prior_infrastructure_errors != prior_errors
                or record.prior_interrupted_runs != prior_interrupted
            )
        ):
            record.prior_infrastructure_errors = list(prior_errors)
            record.prior_interrupted_runs = list(prior_interrupted)
            _atomic_write_record(record_path, record)

        while record is None or record.status == "infra_error":
            if record is not None:
                if len(prior_errors) + 1 >= _MAX_INFRASTRUCTURE_RUNS:
                    _normalize_record_paths(record)
                    record.prior_infrastructure_errors = list(prior_errors)
                    record.prior_interrupted_runs = list(prior_interrupted)
                    _atomic_write_record(record_path, record)
                    _write_final_infrastructure_error(
                        instance_dir,
                        record,
                        len(prior_errors) + 1,
                    )
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
            _normalize_record_paths(record)
            record.prior_infrastructure_errors = list(prior_errors)
            record.prior_interrupted_runs = list(prior_interrupted)
            _atomic_write_record(record_path, record)

        if record.instance_id not in progress_ids:
            _append_progress(pilot_dir, record, candidate_position)
            progress_ids.add(record.instance_id)
        return record

    while index < len(candidates) and ran < n:
        batch: list[tuple[int, Instance]] = []
        while (
            index < len(candidates)
            and ran < n
            and len(batch) < min(concurrency, n - ran)
        ):
            instance = candidates[index]
            index += 1
            batch.append((index, instance))

        if not batch:
            continue
        completed = await asyncio.gather(
            *(
                run_and_log(candidate_position, instance)
                for candidate_position, instance in batch
            ),
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
    "PriorInterruptedRun",
    "run_instance",
    "run_pilot",
]
