from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path

from receipts.models import Receipt
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
        path.write_text(patch, encoding="utf-8")
        attempts.append(
            AttemptResult.model_construct(
                number=number,
                filtered_patch_path=relative,
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
    assert record.judgement.resolved is True
    assert record.judgement.from_fail_to_pass == [TARGET]
    assert record.judgement.failed_from_fail_to_pass == []
    assert record.judgement.failed_from_pass_to_pass == []
    assert TARGET.encode() in _assert_log_matches(run_dir, record)


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
