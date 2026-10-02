"""Grade agent attempts with the official SWE-rebench V2 rule."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

from receipts.models import Receipt
from receipts.orchestrate import RunResult
from receipts.sandbox.protocol import Executor
from receipts.swerebench import (
    Instance,
    OfficialJudgement,
    official_command,
    official_resolved,
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


def _write_log(run_dir: Path, attempt: int, output: bytes) -> tuple[str, str]:
    relative = f"official/attempt-{attempt}.log"
    path = run_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)
    return relative, hashlib.sha256(output).hexdigest()


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
        (branch,) = await ex.fork(result.checkpoint, 1, prefix="official")
        try:
            patch_bytes = (run_dir / attempt.filtered_patch_path).read_bytes()
            patch_sha256 = hashlib.sha256(patch_bytes).hexdigest()
            if (
                attempt.filtered_sha256 is not None
                and patch_sha256 != attempt.filtered_sha256
            ):
                log_path, log_sha256 = _write_log(run_dir, attempt.number, b"")
                records.append(
                    OfficialRecord(
                        attempt=attempt.number,
                        branch_id=branch.id,
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
            patch = patch_bytes.decode("utf-8")
            applied = await ex.apply_patch(branch, patch)

            if applied.timed_out or applied.exit_code != 0:
                output = _apply_failure_output(applied)
                log_path, log_sha256 = _write_log(run_dir, attempt.number, output)
                detail = applied.stderr_tail.strip()
                infra_error = (
                    "patch apply failed "
                    f"(exit {applied.exit_code}, timed_out={applied.timed_out})"
                )
                if detail:
                    infra_error += f": {detail}"
                records.append(
                    OfficialRecord(
                        attempt=attempt.number,
                        branch_id=branch.id,
                        apply_exit_code=applied.exit_code,
                        test_exit_code=None,
                        timed_out=applied.timed_out,
                        log_path=log_path,
                        log_sha256=log_sha256,
                        judgement=official_resolved(instance, ""),
                        infra_error=infra_error,
                        applied_sha256=applied.patch_sha256,
                        read_sha256=patch_sha256,
                    ),
                )
                continue

            tested = await ex.run(
                branch,
                official_command(instance),
                timeout_s=timeout_s,
            )
            output, log_error = _full_stdout(tested)
            if output is None:
                output = b""
            log_path, log_sha256 = _write_log(run_dir, attempt.number, output)
            judgement = official_resolved(instance, output.decode(errors="replace"))
            infra_error = None
            if log_error is not None:
                judgement = judgement.model_copy(update={"resolved": False})
                infra_error = f"full log unavailable: {log_error}"
            elif tested.timed_out:
                judgement = judgement.model_copy(update={"resolved": False})
                infra_error = f"official test timed out after {timeout_s} seconds"
            records.append(
                OfficialRecord(
                    attempt=attempt.number,
                    branch_id=branch.id,
                    apply_exit_code=applied.exit_code,
                    test_exit_code=tested.exit_code,
                    timed_out=tested.timed_out,
                    log_path=log_path,
                    log_sha256=log_sha256,
                    judgement=judgement,
                    infra_error=infra_error,
                    applied_sha256=applied.patch_sha256,
                    read_sha256=patch_sha256,
                ),
            )
        finally:
            await ex.release(branch)

    return records


__all__ = ["OfficialRecord", "grade_attempts"]
