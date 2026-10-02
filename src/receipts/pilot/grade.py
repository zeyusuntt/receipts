"""Grade agent attempts with the official SWE-rebench V2 rule."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

from receipts.models import Checkpoint, Receipt
from receipts.orchestrate import RunResult
from receipts.sandbox.protocol import Executor
from receipts.swerebench import (
    Instance,
    OfficialJudgement,
    official_command,
    official_resolved,
    parse_log_pytest,
)


class OfficialRecord(BaseModel):
    attempt: int
    branch_id: str
    apply_exit_code: int | None
    test_exit_code: int | None
    timed_out: bool
    log_path: str
    log_sha256: str
    judgement: OfficialJudgement
    infra_error: str | None = None
    applied_sha256: str | None = None
    read_sha256: str | None = None


class Gradeability(BaseModel):
    gradeable: bool
    reason: str | None
    failing_pass_to_pass: list[str]
    passing_fail_to_pass: list[str]
    infra_error: str | None


def gradeability(
    instance: Instance,
    record: OfficialRecord,
    log_text: str,
) -> Gradeability:
    """Apply selection rule 5 to the exact ids parsed by the official grader."""

    outcomes = parse_log_pytest(log_text)
    failing_pass_to_pass = [
        node_id
        for node_id in instance.pass_to_pass
        if outcomes.get(node_id) != "PASSED"
    ]
    passing_fail_to_pass = [
        node_id
        for node_id in instance.fail_to_pass
        if outcomes.get(node_id) == "PASSED"
    ]
    if record.infra_error is not None:
        return Gradeability(
            gradeable=False,
            reason=record.infra_error,
            failing_pass_to_pass=failing_pass_to_pass,
            passing_fail_to_pass=passing_fail_to_pass,
            infra_error=record.infra_error,
        )

    reasons: list[str] = []
    if failing_pass_to_pass:
        reasons.append(
            "PASS_TO_PASS did not pass: " + ", ".join(failing_pass_to_pass),
        )
    if passing_fail_to_pass:
        reasons.append(
            "FAIL_TO_PASS already passed: " + ", ".join(passing_fail_to_pass),
        )
    return Gradeability(
        gradeable=not reasons,
        reason=(
            None
            if not reasons
            else "not gradeable in this environment: " + "; ".join(reasons)
        ),
        failing_pass_to_pass=failing_pass_to_pass,
        passing_fail_to_pass=passing_fail_to_pass,
        infra_error=None,
    )


def _full_stdout(receipt: Receipt) -> tuple[bytes | None, str | None]:
    if receipt.log_path is None:
        return None, "receipt has no log_path"
    try:
        return Path(receipt.log_path).read_bytes(), None
    except OSError as exc:
        return None, str(exc)


def _apply_failure_output(receipt: Receipt) -> bytes:
    output, _ = _full_stdout(receipt)
    if output is None:
        output = receipt.stdout_tail.encode()
    stderr = receipt.stderr_tail.encode()
    if not stderr:
        return output
    if output and not output.endswith(b"\n"):
        output += b"\n"
    return output + stderr


def _write_log(run_dir: Path, log_name: str, output: bytes) -> tuple[str, str]:
    relative = Path(log_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("official log name must be relative to the run directory")
    path = run_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)
    return relative.as_posix(), hashlib.sha256(output).hexdigest()


async def grade_patch(
    ex: Executor,
    checkpoint: Checkpoint,
    instance: Instance,
    patch_text: str,
    run_dir: Path,
    log_name: str,
    timeout_s: int = 600,
) -> OfficialRecord:
    """Officially grade one patch on a fresh fork and retain its full log."""

    (branch,) = await ex.fork(checkpoint, 1, prefix="official")
    read_sha256 = hashlib.sha256(patch_text.encode()).hexdigest()
    try:
        applied = await ex.apply_patch(branch, patch_text)
        if applied.timed_out or applied.exit_code != 0:
            output = _apply_failure_output(applied)
            log_path, log_sha256 = _write_log(run_dir, log_name, output)
            detail = applied.stderr_tail.strip()
            infra_error = (
                "patch apply failed "
                f"(exit {applied.exit_code}, timed_out={applied.timed_out})"
            )
            if detail:
                infra_error += f": {detail}"
            return OfficialRecord(
                attempt=0,
                branch_id=branch.id,
                apply_exit_code=applied.exit_code,
                test_exit_code=None,
                timed_out=applied.timed_out,
                log_path=log_path,
                log_sha256=log_sha256,
                judgement=official_resolved(instance, ""),
                infra_error=infra_error,
                applied_sha256=applied.patch_sha256,
                read_sha256=read_sha256,
            )

        tested = await ex.run(
            branch,
            official_command(instance),
            timeout_s=timeout_s,
        )
        output, log_error = _full_stdout(tested)
        if output is None:
            output = b""
        log_path, log_sha256 = _write_log(run_dir, log_name, output)
        judgement = official_resolved(instance, output.decode(errors="replace"))
        infra_error = None
        if log_error is not None:
            judgement = judgement.model_copy(update={"resolved": False})
            infra_error = f"full log unavailable: {log_error}"
        elif tested.timed_out:
            judgement = judgement.model_copy(update={"resolved": False})
            infra_error = f"official test timed out after {timeout_s} seconds"
        return OfficialRecord(
            attempt=0,
            branch_id=branch.id,
            apply_exit_code=applied.exit_code,
            test_exit_code=tested.exit_code,
            timed_out=tested.timed_out,
            log_path=log_path,
            log_sha256=log_sha256,
            judgement=judgement,
            infra_error=infra_error,
            applied_sha256=applied.patch_sha256,
            read_sha256=read_sha256,
        )
    finally:
        await ex.release(branch)


async def grade_attempts(
    ex: Executor,
    result: RunResult,
    run_dir: Path,
    instance: Instance,
    timeout_s: int = 600,
) -> list[OfficialRecord]:
    """Run official grading once for every recorded attempt."""

    records: list[OfficialRecord] = []
    for attempt in result.attempts:
        patch_bytes = (run_dir / attempt.filtered_patch_path).read_bytes()
        patch_sha256 = hashlib.sha256(patch_bytes).hexdigest()
        log_name = f"official/attempt-{attempt.number}.log"
        if (
            attempt.filtered_sha256 is not None
            and patch_sha256 != attempt.filtered_sha256
        ):
            log_path, log_sha256 = _write_log(run_dir, log_name, b"")
            records.append(
                OfficialRecord(
                    attempt=attempt.number,
                    branch_id="not-run",
                    apply_exit_code=None,
                    test_exit_code=None,
                    timed_out=False,
                    log_path=log_path,
                    log_sha256=log_sha256,
                    judgement=official_resolved(instance, ""),
                    infra_error=(
                        "filtered.diff does not match the digest recorded at the gate"
                    ),
                    read_sha256=patch_sha256,
                ),
            )
            continue
        record = await grade_patch(
            ex,
            result.checkpoint,
            instance,
            patch_bytes.decode("utf-8"),
            run_dir,
            log_name,
            timeout_s=timeout_s,
        )
        records.append(record.model_copy(update={"attempt": attempt.number}))

    return records


__all__ = [
    "Gradeability",
    "OfficialRecord",
    "grade_attempts",
    "grade_patch",
    "gradeability",
]
