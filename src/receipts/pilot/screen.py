"""Screen SWE-rebench candidates without running an agent or model."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import AbstractSet, Any, Literal

from pydantic import BaseModel, Field

from receipts.pilot.grade import Gradeability, grade_patch, gradeability
from receipts.pilot.runner import (
    ExecutorFactory,
    _BaselineGuard,
    _MAX_INFRASTRUCTURE_RUNS,
    _PREREGISTERED_BASELINE_LIMIT_S,
    _close_executor,
    _run_id,
    _sandbox_usage,
)
from receipts.swerebench import (
    Instance,
    UnparseableTestPatch,
    to_task,
)
from receipts.verify.run import (
    BaselineBroken,
    BaselineTooSlow,
    TargetNotFailing,
    establish_baseline,
)


ScreenOutcome = Literal["included", "excluded", "infra_error"]
ScreenRule = Literal["4", "5"]


class ScreenRecord(BaseModel):
    position: int = Field(ge=1)
    instance_id: str
    outcome: ScreenOutcome
    rule: ScreenRule | None
    reason: str | None
    failing_ids: list[str]
    official_log_path: str | None
    official_log_sha256: str | None
    sandbox_usage: list[dict[str, Any]]
    wall_seconds: float = Field(ge=0)
    run_number: int = Field(ge=1)
    recovered_torn_ledger_sha256: str | None = None


def _repository_root() -> Path:
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def _relative_to_repository(path: Path) -> str:
    return Path(os.path.relpath(path.resolve(), _repository_root())).as_posix()


def _failing_rule_4_ids(exc: Exception) -> list[str]:
    if isinstance(exc, TargetNotFailing):
        return list(exc.node_ids)
    return []


def _write_error(run_dir: Path, detail: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "error.txt").write_text(detail, encoding="utf-8")


async def _screen_once(
    make_executor: ExecutorFactory,
    instance: Instance,
    position: int,
    run_number: int,
    run_dir: Path,
    timeout_s: int,
) -> ScreenRecord:
    started = time.monotonic()
    run_dir.mkdir(parents=True, exist_ok=False)
    executor: Any = None
    base: Any = None
    original_run_pytest: Any = None
    pytest_replaced = False
    outcome: ScreenOutcome = "infra_error"
    rule: ScreenRule | None = None
    reason: str | None = None
    failing_ids: list[str] = []
    official_log_path: str | None = None
    official_log_sha256: str | None = None
    error_detail: str | None = None
    sandbox_usage: list[dict[str, Any]] = []

    try:
        executor = make_executor(_run_id(instance.instance_id))
        original_run_pytest = getattr(executor, "run_pytest", None)
        if original_run_pytest is not None:
            setattr(
                executor,
                "run_pytest",
                _BaselineGuard(
                    original_run_pytest,
                    _PREREGISTERED_BASELINE_LIMIT_S,
                ),
            )
            pytest_replaced = True

        task = to_task(instance)
        base = await executor.prepare(task.source)
        effective_spec_paths = sorted(
            set(task.spec_paths).union(
                node_id.split("::", 1)[0]
                for node_id in task.spec_tests
            ),
        )
        await establish_baseline(
            executor,
            base,
            task.suite_scope,
            task.spec_tests,
            _PREREGISTERED_BASELINE_LIMIT_S * 2,
            spec_paths=effective_spec_paths,
        )
        snapshot = await executor.snapshot(base)
        if (
            snapshot.timed_out
            or snapshot.exit_code != 0
            or snapshot.snapshot_sha is None
        ):
            raise RuntimeError(
                "snapshot failed "
                f"(exit {snapshot.exit_code}, timed_out={snapshot.timed_out})",
            )
        checkpoint = await executor.checkpoint(base)
        await executor.release(base)
        base = None

        official = await grade_patch(
            executor,
            checkpoint,
            instance,
            "",
            run_dir,
            "official.log",
            timeout_s=timeout_s,
        )
        official_path = run_dir / official.log_path
        log_text = official_path.read_bytes().decode(errors="replace")
        official_log_path = _relative_to_repository(official_path)
        official_log_sha256 = official.log_sha256
        result = gradeability(instance, official, log_text)
        if result.infra_error is not None:
            reason = result.infra_error
        elif result.gradeable:
            outcome = "included"
        else:
            outcome = "excluded"
            rule = "5"
            reason = result.reason
            failing_ids = [
                *result.failing_pass_to_pass,
                *result.passing_fail_to_pass,
            ]
    except (BaselineBroken, BaselineTooSlow, TargetNotFailing, UnparseableTestPatch) as exc:
        outcome = "excluded"
        rule = "4"
        reason = str(exc)
        failing_ids = _failing_rule_4_ids(exc)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        error_detail = traceback.format_exc()
    finally:
        cleanup_errors: list[str] = []
        if executor is not None and pytest_replaced:
            setattr(executor, "run_pytest", original_run_pytest)
        if executor is not None and base is not None:
            try:
                await executor.release(base)
            except Exception as exc:
                cleanup_errors.append(f"base release failed: {type(exc).__name__}: {exc}")
        if executor is not None:
            try:
                await _close_executor(executor)
            except Exception as exc:
                cleanup_errors.append(f"executor close failed: {type(exc).__name__}: {exc}")
            try:
                sandbox_usage = _sandbox_usage(executor)
            except Exception as exc:
                cleanup_errors.append(
                    f"sandbox usage failed: {type(exc).__name__}: {exc}",
                )
        if cleanup_errors:
            outcome = "infra_error"
            rule = None
            failing_ids = []
            reason = "; ".join(cleanup_errors)
            error_detail = (error_detail or "") + reason + "\n"

    if outcome == "infra_error":
        rule = None
        failing_ids = []
        if error_detail is not None:
            _write_error(run_dir, error_detail)
    return ScreenRecord(
        position=position,
        instance_id=instance.instance_id,
        outcome=outcome,
        rule=rule,
        reason=reason,
        failing_ids=failing_ids,
        official_log_path=official_log_path,
        official_log_sha256=official_log_sha256,
        sandbox_usage=sandbox_usage,
        wall_seconds=time.monotonic() - started,
        run_number=run_number,
    )


def _read_ledger(path: Path) -> list[ScreenRecord]:
    if not path.is_file():
        return []
    content = path.read_bytes()
    rows: list[ScreenRecord] = []
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        try:
            record = ScreenRecord.model_validate_json(line)
        except (json.JSONDecodeError, ValueError) as error:
            digest = hashlib.sha256(line).hexdigest()
            if index + 1 < len(lines):
                try:
                    recovery = ScreenRecord.model_validate_json(lines[index + 1])
                except (json.JSONDecodeError, ValueError):
                    raise error
                if recovery.recovered_torn_ledger_sha256 == digest:
                    rows.append(recovery)
                    index += 2
                    continue
            if index == len(lines) - 1 and not content.endswith(b"\n"):
                break
            raise error
        rows.append(record)
        index += 1
    return rows


def _append_ledger(path: Path, record: ScreenRecord) -> ScreenRecord:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_bytes() if path.is_file() else b""
    torn_fragment = content.rsplit(b"\n", 1)[-1] if content else b""
    if torn_fragment:
        record = record.model_copy(
            update={
                "recovered_torn_ledger_sha256": hashlib.sha256(
                    torn_fragment,
                ).hexdigest(),
            },
        )
    with path.open("ab") as writer:
        if torn_fragment:
            writer.write(b"\n")
        writer.write(record.model_dump_json().encode() + b"\n")
        writer.flush()
        os.fsync(writer.fileno())
    return record


def _terminal(record: ScreenRecord) -> bool:
    return (
        record.outcome in {"included", "excluded"}
        or record.run_number >= _MAX_INFRASTRUCTURE_RUNS
    )


def _last_rows(rows: Sequence[ScreenRecord]) -> dict[tuple[int, str], ScreenRecord]:
    latest: dict[tuple[int, str], ScreenRecord] = {}
    for row in rows:
        key = (row.position, row.instance_id)
        current = latest.get(key)
        if current is None or row.run_number >= current.run_number:
            latest[key] = row
    return latest


async def screen_candidates(
    make_executor: ExecutorFactory,
    candidates: Sequence[Instance],
    ledger_path: Path,
    *,
    start: int,
    exclude: AbstractSet[str],
    want: int,
    concurrency: int = 1,
    timeout_s: int = 600,
) -> list[str]:
    """Append screening runs and return the first included ids by position."""

    if start < 1:
        raise ValueError("start must be at least 1")
    if want < 0:
        raise ValueError("want must be non-negative")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if len({instance.instance_id for instance in candidates}) != len(candidates):
        raise ValueError("candidate ids must be unique")
    if want == 0:
        return []

    entries = [
        (position, instance)
        for position, instance in enumerate(candidates, start=1)
        if position >= start and instance.instance_id not in exclude
    ]
    valid_positions = {
        position: instance.instance_id
        for position, instance in entries
    }
    rows = _read_ledger(ledger_path)
    for row in rows:
        expected_id = valid_positions.get(row.position)
        if expected_id is not None and row.instance_id != expected_id:
            raise ValueError(
                "screening ledger does not match the candidate order at "
                f"position {row.position}",
            )

    screen_root = ledger_path.with_suffix("")
    append_lock = asyncio.Lock()

    async def run_to_terminal(position: int, instance: Instance) -> None:
        nonlocal rows
        relevant = [
            row
            for row in rows
            if row.position == position and row.instance_id == instance.instance_id
        ]
        recorded_numbers = {row.run_number for row in relevant}
        instance_root = screen_root / instance.instance_id
        orphaned: list[tuple[int, Path]] = []
        if instance_root.is_dir():
            for path in instance_root.iterdir():
                if not path.is_dir() or not path.name.startswith("run-"):
                    continue
                rendered_number = path.name.removeprefix("run-")
                if not rendered_number.isdigit():
                    continue
                number = int(rendered_number)
                if (
                    number <= _MAX_INFRASTRUCTURE_RUNS
                    and number not in recorded_numbers
                ):
                    orphaned.append((number, path))
        for number, path in sorted(orphaned):
            log_path = path / "official.log"
            orphan = ScreenRecord(
                position=position,
                instance_id=instance.instance_id,
                outcome="infra_error",
                rule=None,
                reason="interrupted before the screening run was recorded",
                failing_ids=[],
                official_log_path=(
                    _relative_to_repository(log_path)
                    if log_path.is_file()
                    else None
                ),
                official_log_sha256=(
                    hashlib.sha256(log_path.read_bytes()).hexdigest()
                    if log_path.is_file()
                    else None
                ),
                sandbox_usage=[],
                wall_seconds=0,
                run_number=number,
            )
            async with append_lock:
                orphan = _append_ledger(ledger_path, orphan)
                rows.append(orphan)
            relevant.append(orphan)
        relevant.sort(key=lambda row: row.run_number)
        if relevant and _terminal(relevant[-1]):
            return
        run_number = max((row.run_number for row in relevant), default=0) + 1
        while run_number <= _MAX_INFRASTRUCTURE_RUNS:
            run_dir = screen_root / instance.instance_id / f"run-{run_number}"
            record = await _screen_once(
                make_executor,
                instance,
                position,
                run_number,
                run_dir,
                timeout_s,
            )
            async with append_lock:
                record = _append_ledger(ledger_path, record)
                rows.append(record)
            if record.outcome != "infra_error":
                return
            run_number += 1

    while True:
        entry_keys = {
            (position, instance.instance_id)
            for position, instance in entries
        }
        latest = {
            key: row
            for key, row in _last_rows(rows).items()
            if key in entry_keys
        }
        included = sorted(
            (
                row
                for row in latest.values()
                if row.outcome == "included"
            ),
            key=lambda row: row.position,
        )
        terminal_keys = {
            key
            for key, row in latest.items()
            if _terminal(row)
        }

        if len(included) >= want:
            cutoff = included[want - 1].position
            pending = [
                (position, instance)
                for position, instance in entries
                if position <= cutoff
                and (position, instance.instance_id) not in terminal_keys
            ]
            if not pending:
                return [row.instance_id for row in included[:want]]
        else:
            pending = [
                (position, instance)
                for position, instance in entries
                if (position, instance.instance_id) not in terminal_keys
            ]
            if not pending:
                return [row.instance_id for row in included]
            needed = want - len(included)
            pending = pending[:max(1, min(concurrency, needed))]

        await asyncio.gather(
            *(run_to_terminal(position, instance) for position, instance in pending[:concurrency]),
        )


__all__ = [
    "Gradeability",
    "ScreenRecord",
    "gradeability",
    "screen_candidates",
]
