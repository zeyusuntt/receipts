from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path

import pytest

import receipts.pilot.grade as pilot_grade
from receipts.models import Receipt, Verdict
from receipts.orchestrate import AttemptResult, RunResult
from receipts.pilot.grade import grade_attempts
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import RepoAtCommit
from receipts.sandbox.sink import MemorySink
from receipts.swerebench import Instance
from tests.fixtures.repo_factory import CALC, make_repo


TARGET = "tests/test_calc.py::test_sub"
PROTECTED = "tests/test_calc.py::test_add"
FIXED_CALC = '''def add(a, b):
    return a + b


def sub(a, b):
    return a - b
'''
REGRESSED_CALC = '''def add(a, b):
    return a - b


def sub(a, b):
    return a - b
'''


def _source_patch(updated: str) -> str:
    body = "".join(
        unified_diff(
            CALC.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="a/calc/__init__.py",
            tofile="b/calc/__init__.py",
        ),
    )
    return "diff --git a/calc/__init__.py b/calc/__init__.py\n" + body


async def _grading_case(tmp_path: Path, patches: list[str]):
    repo = make_repo(tmp_path / "source")
    executor = LocalExecutor(
        tmp_path / "executor",
        MemorySink(),
        run_id="official-grade-test",
    )
    base = await executor.prepare(
        RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"),
    )
    snapshot = await executor.snapshot(base)
    assert snapshot.exit_code == 0
    checkpoint = await executor.checkpoint(base)

    run_dir = tmp_path / "run"
    attempts = []
    for number, patch in enumerate(patches, start=1):
        relative = f"attempts/{number}/filtered.diff"
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        patch_bytes = patch.encode("utf-8")
        path.write_bytes(patch_bytes)
        attempts.append(
            AttemptResult.model_construct(
                number=number,
                filtered_patch_path=relative,
                filtered_sha256=hashlib.sha256(patch_bytes).hexdigest(),
            ),
        )

    result = RunResult.model_construct(
        checkpoint=checkpoint,
        attempts=attempts,
    )
    instance = Instance(
        instance_id="fixture__calc-1",
        repo="fixture/calc",
        base_commit="HEAD",
        image_name="fixture/calc:latest",
        test_patch="",
        fail_to_pass=[TARGET],
        pass_to_pass=[PROTECTED],
        test_cmd="pytest -rA tests",
        problem_statement="Fix subtraction without breaking addition.",
    )
    return executor, result, run_dir, instance


def _assert_log_matches(run_dir: Path, record) -> bytes:
    assert record.log_path == f"official/attempt-{record.attempt}.log"
    content = (run_dir / record.log_path).read_bytes()
    assert hashlib.sha256(content).hexdigest() == record.log_sha256
    return content


async def test_honest_patch_grades_resolved_and_writes_hashed_log(tmp_path: Path):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC)],
    )

    records = await grade_attempts(executor, result, run_dir, instance)

    assert len(records) == 1
    record = records[0]
    assert record.attempt == 1
    assert record.branch_id == "official1"
    assert record.apply_exit_code == 0
    assert record.test_exit_code == 0
    assert record.timed_out is False
    assert record.infra_error is None
    assert record.applied_sha256 == result.attempts[0].filtered_sha256
    assert record.read_sha256 == result.attempts[0].filtered_sha256
    assert record.judgement.resolved is True
    assert record.judgement.from_fail_to_pass == [TARGET]
    assert record.judgement.failed_from_fail_to_pass == []
    assert record.judgement.failed_from_pass_to_pass == []
    assert TARGET.encode() in _assert_log_matches(run_dir, record)


class _ApplyRecordingExecutor:
    def __init__(self, inner: LocalExecutor) -> None:
        self.inner = inner
        self.apply_calls = 0

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    async def apply_patch(self, branch, patch_text):
        self.apply_calls += 1
        return await self.inner.apply_patch(branch, patch_text)


async def test_mutated_filtered_patch_is_rejected_before_apply(tmp_path: Path):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC)],
    )
    filtered_path = run_dir / result.attempts[0].filtered_patch_path
    filtered_path.write_bytes(filtered_path.read_bytes() + b"# mutated after gate\n")
    recording = _ApplyRecordingExecutor(executor)

    (record,) = await grade_attempts(recording, result, run_dir, instance)

    assert recording.apply_calls == 0
    assert record.apply_exit_code is None
    assert record.test_exit_code is None
    assert record.applied_sha256 is None
    assert record.read_sha256 == hashlib.sha256(filtered_path.read_bytes()).hexdigest()
    assert record.read_sha256 != result.attempts[0].filtered_sha256
    assert record.infra_error == (
        "filtered.diff does not match the digest recorded at the gate"
    )
    assert record.judgement.resolved is False


async def test_attempt_without_recorded_digest_is_graded_as_before(tmp_path: Path):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC)],
    )
    result.attempts[0].filtered_sha256 = None
    recording = _ApplyRecordingExecutor(executor)

    (record,) = await grade_attempts(recording, result, run_dir, instance)

    assert recording.apply_calls == 1
    assert record.infra_error is None
    assert record.judgement.resolved is True


async def test_patch_that_breaks_protected_test_grades_not_resolved(tmp_path: Path):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(REGRESSED_CALC)],
    )

    (record,) = await grade_attempts(executor, result, run_dir, instance)

    assert record.apply_exit_code == 0
    assert record.test_exit_code == 1
    assert record.infra_error is None
    assert record.judgement.resolved is False
    assert record.judgement.from_fail_to_pass == [TARGET]
    assert record.judgement.failed_from_pass_to_pass == [PROTECTED]
    _assert_log_matches(run_dir, record)


async def test_empty_patch_grades_not_resolved(tmp_path: Path):
    executor, result, run_dir, instance = await _grading_case(tmp_path, [""])

    (record,) = await grade_attempts(executor, result, run_dir, instance)

    assert record.apply_exit_code == 0
    assert record.test_exit_code == 1
    assert record.infra_error is None
    assert record.judgement.resolved is False
    assert record.judgement.failed_from_fail_to_pass == [TARGET]
    _assert_log_matches(run_dir, record)


async def test_patch_that_does_not_apply_is_retained_as_infrastructure_error(
    tmp_path: Path,
):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        ["not a patch\n"],
    )

    (record,) = await grade_attempts(executor, result, run_dir, instance)

    assert record.apply_exit_code != 0
    assert record.test_exit_code is None
    assert record.timed_out is False
    assert record.infra_error is not None
    assert "patch apply failed" in record.infra_error
    assert record.judgement.resolved is False
    assert record.judgement.failed_from_fail_to_pass == [TARGET]
    assert _assert_log_matches(run_dir, record)


class _TimeoutExecutor:
    def __init__(self, inner: LocalExecutor, log_path: Path) -> None:
        self.inner = inner
        self.log_path = log_path

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    async def run(self, branch, cmd: str, timeout_s: int) -> Receipt:
        output = f"PASSED {TARGET}\nPASSED {PROTECTED}\n".encode()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_bytes(output)
        started = datetime.now(timezone.utc)
        before = branch.head
        branch.head = "timed-out-image"
        return Receipt(
            receipt_id=f"{branch.id}-2",
            seq=2,
            branch_id=branch.id,
            kind="command",
            cmd=cmd,
            exit_code=None,
            stdout_tail=output.decode(),
            stdout_sha256=hashlib.sha256(output).hexdigest(),
            log_path=str(self.log_path),
            started_at=started,
            duration_s=float(timeout_s),
            timed_out=True,
            image_before=before,
            image_after=branch.head,
        )


async def test_timeout_is_infrastructure_error_even_if_log_looks_resolved(
    tmp_path: Path,
):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC)],
    )
    timed_out = _TimeoutExecutor(executor, tmp_path / "timeout" / "full.log")

    (record,) = await grade_attempts(
        timed_out,
        result,
        run_dir,
        instance,
        timeout_s=7,
    )

    assert record.apply_exit_code == 0
    assert record.test_exit_code is None
    assert record.timed_out is True
    assert record.infra_error == "official test timed out after 7 seconds"
    assert record.judgement.resolved is False
    assert _assert_log_matches(run_dir, record) == (
        f"PASSED {TARGET}\nPASSED {PROTECTED}\n".encode()
    )


async def test_official_timeout_after_witness_timeout_is_attempt_outcome(
    tmp_path: Path,
):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC)],
    )
    result.attempts[0].verdict = Verdict(
        branch_id="agent1",
        status="ERROR",
        predicates=[],
        claim_audit="no_claim",
        claim_evidence="branch ended without a finish call",
        error="verification timed out after 7s",
        error_kind="attempt",
    )
    timed_out = _TimeoutExecutor(executor, tmp_path / "timeout" / "full.log")

    (record,) = await grade_attempts(
        timed_out,
        result,
        run_dir,
        instance,
        timeout_s=7,
    )

    assert record.timed_out is True
    assert record.judgement.resolved is False
    assert record.infra_error is None
    assert record.note == "official run timed out, as the witness did"


class _UnavailableLogExecutor:
    def __init__(self, inner: LocalExecutor, log_path: Path | None) -> None:
        self.inner = inner
        self.log_path = log_path

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    async def run(self, branch, cmd: str, timeout_s: int) -> Receipt:
        output = f"PASSED {TARGET}\nPASSED {PROTECTED}\n".encode()
        started = datetime.now(timezone.utc)
        before = branch.head
        branch.head = "unavailable-log-image"
        return Receipt(
            receipt_id=f"{branch.id}-2",
            seq=2,
            branch_id=branch.id,
            kind="command",
            cmd=cmd,
            exit_code=0,
            stdout_tail=output.decode(),
            stdout_sha256=hashlib.sha256(output).hexdigest(),
            log_path=str(self.log_path) if self.log_path is not None else None,
            started_at=started,
            duration_s=0.1,
            timed_out=False,
            image_before=before,
            image_after=branch.head,
        )


async def test_missing_full_log_is_infrastructure_error_and_tail_is_not_graded(
    tmp_path: Path,
):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC)],
    )
    unavailable = _UnavailableLogExecutor(executor, None)

    (record,) = await grade_attempts(unavailable, result, run_dir, instance)

    assert record.test_exit_code == 0
    assert record.infra_error == "full log unavailable: receipt has no log_path"
    assert record.judgement.resolved is False


async def test_deleted_full_log_is_infrastructure_error_and_tail_is_not_graded(
    tmp_path: Path,
):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC)],
    )
    deleted_log = tmp_path / "deleted" / "full.log"
    deleted_log.parent.mkdir(parents=True)
    deleted_log.write_text("deleted", encoding="utf-8")
    deleted_log.unlink()
    unavailable = _UnavailableLogExecutor(executor, deleted_log)

    (record,) = await grade_attempts(unavailable, result, run_dir, instance)

    assert record.test_exit_code == 0
    assert record.infra_error is not None
    assert record.infra_error.startswith("full log unavailable: ")
    assert str(deleted_log) in record.infra_error
    assert record.judgement.resolved is False


class _ReleaseRecordingExecutor:
    def __init__(self, inner: LocalExecutor, run_dir: Path) -> None:
        self.inner = inner
        self.run_dir = run_dir
        self.released: list[tuple[str, bool]] = []

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    async def release(self, branch) -> None:
        attempt = len(self.released) + 1
        log_exists = (
            self.run_dir / "official" / f"attempt-{attempt}.log"
        ).is_file()
        self.released.append((branch.id, log_exists))
        await self.inner.release(branch)


async def test_releases_official_branches_in_attempt_order_after_logs_are_written(
    tmp_path: Path,
):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC), "not a patch\n"],
    )
    recording = _ReleaseRecordingExecutor(executor, run_dir)

    records = await grade_attempts(recording, result, run_dir, instance)

    assert [record.branch_id for record in records] == ["official1", "official2"]
    assert recording.released == [("official1", True), ("official2", True)]


class _ReleaseFailingExecutor:
    def __init__(self, inner: LocalExecutor) -> None:
        self.inner = inner

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    async def release(self, branch) -> None:
        await self.inner.release(branch)
        raise RuntimeError("official release failed")


async def test_release_failure_after_official_result_is_recorded(tmp_path: Path):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC)],
    )

    (record,) = await grade_attempts(
        _ReleaseFailingExecutor(executor),
        result,
        run_dir,
        instance,
    )

    assert record.judgement.resolved is True
    assert record.infra_error is None
    assert record.cleanup_error == "RuntimeError: official release failed"


class _CancellingApplyWithReleaseFailureExecutor:
    def __init__(self, inner: LocalExecutor) -> None:
        self.inner = inner

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    async def apply_patch(self, branch, patch_text):
        raise asyncio.CancelledError

    async def release(self, branch) -> None:
        await self.inner.release(branch)
        raise RuntimeError("official release failed during cancellation")


async def test_release_failure_does_not_replace_official_cancellation(
    tmp_path: Path,
):
    executor, result, run_dir, instance = await _grading_case(tmp_path, [])

    with pytest.raises(asyncio.CancelledError) as raised:
        await pilot_grade.grade_patch(
            _CancellingApplyWithReleaseFailureExecutor(executor),
            result.checkpoint,
            instance,
            "",
            run_dir,
            "official.log",
        )

    assert raised.value.__notes__ == [
        "official release also failed: RuntimeError: "
        "official release failed during cancellation",
    ]


async def test_witness_apply_digest_mismatch_is_rejected_before_official_apply(
    tmp_path: Path,
):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC)],
    )
    result.attempts[0].witness_apply_sha256 = "f" * 64
    recording = _ApplyRecordingExecutor(executor)

    (record,) = await grade_attempts(recording, result, run_dir, instance)

    assert recording.apply_calls == 0
    assert record.branch_id == "not-run"
    assert record.infra_error == (
        "witness apply digest does not match the filtered patch digest"
    )
    assert record.judgement.resolved is False


class _ApplyDigestMismatchExecutor:
    def __init__(self, inner: LocalExecutor) -> None:
        self.inner = inner
        self.run_calls = 0

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    async def apply_patch(self, branch, patch_text):
        receipt = await self.inner.apply_patch(branch, patch_text)
        return receipt.model_copy(update={"patch_sha256": "f" * 64})

    async def run(self, branch, cmd: str, timeout_s: int):
        self.run_calls += 1
        return await self.inner.run(branch, cmd, timeout_s)


async def test_official_apply_digest_mismatch_does_not_run_tests(tmp_path: Path):
    executor, result, run_dir, instance = await _grading_case(
        tmp_path,
        [_source_patch(FIXED_CALC)],
    )
    mismatching = _ApplyDigestMismatchExecutor(executor)

    (record,) = await grade_attempts(mismatching, result, run_dir, instance)

    assert mismatching.run_calls == 0
    assert record.apply_exit_code == 0
    assert record.test_exit_code is None
    assert record.applied_sha256 == "f" * 64
    assert record.read_sha256 == result.attempts[0].filtered_sha256
    assert record.infra_error == (
        "official apply digest does not match the patch bytes"
    )
    assert record.judgement.resolved is False


async def test_grade_patch_empty_patch_uses_fresh_fork_and_releases_it(
    tmp_path: Path,
):
    executor, result, run_dir, instance = await _grading_case(tmp_path, [])

    record = await pilot_grade.grade_patch(
        executor,
        result.checkpoint,
        instance,
        "",
        run_dir,
        "screen/official.log",
    )

    assert record.attempt == 0
    assert record.branch_id == "official1"
    assert record.apply_exit_code == 0
    assert record.test_exit_code == 1
    assert record.infra_error is None
    assert record.read_sha256 == hashlib.sha256(b"").hexdigest()
    assert record.applied_sha256 == record.read_sha256
    assert record.judgement.resolved is False
    assert record.log_path == "screen/official.log"
    content = (run_dir / record.log_path).read_bytes()
    assert content
    assert hashlib.sha256(content).hexdigest() == record.log_sha256
    assert "official1" in executor._released_branches
