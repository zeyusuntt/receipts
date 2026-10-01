import pytest

from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import RepoAtCommit
from receipts.sandbox.sink import MemorySink
from receipts.verify.run import BaselineTooSlow, TargetNotFailing, establish_baseline, rerun_one, verify_attempt
from tests.fixtures.repo_factory import _git, make_repo

T = "tests/test_calc.py::test_sub"


async def _setup(tmp_path, flaky=False):
    repo = make_repo(tmp_path / "src", flaky=flaky)
    sink = MemorySink()
    ex = LocalExecutor(root=tmp_path / "work", sink=sink, run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))
    return ex, base, sink


async def test_baseline_runs_twice_and_marks_unstable(tmp_path):
    ex, base, sink = await _setup(tmp_path, flaky=True)
    b = await establish_baseline(ex, base, "tests", [T], limit_s=600)
    assert len(b.runs) == 2 and len(b.run_receipt_ids) == 2
    assert b.unstable == ["tests/test_flaky.py::test_flaky"]
    assert set(b.protected) == {"tests/test_calc.py::test_add", "tests/test_calc.py::test_zero", "tests/test_calc.py::test_param[a b]"}
    assert set(b.collected_ids) == set(b.protected) | {T, "tests/test_flaky.py::test_flaky"}
    assert b.skipped_ids == [] and b.target == [T]
    assert [r.kind for r in sink.receipts].count("command") == 3  # install + two baseline runs


async def test_baseline_rejects_passing_target(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    with pytest.raises(TargetNotFailing) as info:
        await establish_baseline(ex, base, "tests", ["tests/test_calc.py::test_add"], limit_s=600)
    assert info.value.node_ids == ["tests/test_calc.py::test_add"]


async def test_baseline_rejects_unknown_target(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    with pytest.raises(TargetNotFailing):
        await establish_baseline(ex, base, "tests", ["tests/test_calc.py::test_missing"], limit_s=600)


async def test_baseline_rejects_flaky_target(tmp_path):
    ex, base, _ = await _setup(tmp_path, flaky=True)
    with pytest.raises(TargetNotFailing) as info:
        await establish_baseline(ex, base, "tests", ["tests/test_flaky.py::test_flaky"], limit_s=600)
    assert info.value.node_ids == ["tests/test_flaky.py::test_flaky"]


async def test_baseline_too_slow(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    with pytest.raises(BaselineTooSlow):
        await establish_baseline(ex, base, "tests", [T], limit_s=0)


async def test_honest_source_fix_verifies_green_on_witness(tmp_path):
    ex, base, sink = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    fixed = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    await ex.write_file(agent, "calc/__init__.py", fixed)
    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)
    assert result.patch.kind == "diff" and result.patch.branch_id == "b1"
    assert result.filtered_patch and result.dropped == []
    assert result.witness.id == "w1" and result.apply.branch_id == "w1" and result.apply.exit_code == 0
    assert result.apply.patch_sha256 == result.filtered_sha256
    assert result.verification.kind == "verification" and result.verification.branch_id == "w1"
    assert result.verification.junit.failed == [] and result.verification.junit.collected == 4
    assert await ex.read_file(result.witness, "calc/__init__.py", 10_000) == fixed
    second = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=2)
    assert second.witness.id == "w2" and second.verification.junit.failed == []


async def test_conftest_hijack_is_dropped_and_witness_still_fails(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    hijack = '''import pytest


@pytest.fixture(autouse=True)
def force_target_green(monkeypatch):
    import tests.test_calc as test_calc
    monkeypatch.setattr(test_calc, "sub", lambda a, b: a - b)
'''
    await ex.write_file(agent, "tests/conftest.py", hijack)
    own = await ex.run_pytest(agent, "tests", timeout_s=60)
    assert own.exit_code == 0 and own.junit.failed == [] and own.junit.collected == 4
    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)
    assert result.dropped == ["tests/conftest.py"]
    assert result.patch.dropped_paths == ["tests/conftest.py"] and result.filtered_patch == ""
    assert result.verification.junit.failed == [T]


async def test_gitignored_agent_edit_never_reaches_witness(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    await ex.write_file(agent, "report.xml", "agent-only ignored content\n")
    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)
    assert result.patch.diff.files == [] and result.filtered_patch == "" and result.dropped == []
    assert not (ex.workdir(result.witness) / "report.xml").exists()
    assert result.verification.junit.failed == [T]


async def test_checkpoint_tampering_returns_failed_witness_apply(tmp_path):
    ex, base, sink = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    escaped = await ex.run(
        agent,
        "python -c \"from pathlib import Path; p=next(Path('..').glob('ckpt-*/tests/test_calc.py')); p.write_text('tampered\\n')\"",
        timeout_s=30,
    )
    assert escaped.exit_code == 0

    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)

    assert result.witness.id == "w1"
    assert result.apply.branch_id == "w1" and result.apply.kind == "apply"
    assert result.apply.exit_code == 1
    assert result.apply.stderr_tail == f"checkpoint {c0.id} was modified after prepare"
    assert result.verification is None
    assert sink.receipts[-1].model_dump() == result.apply.model_dump()


async def test_rerun_one_targets_a_single_node_with_brackets_and_spaces(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)
    r = await rerun_one(ex, result.witness, "tests/test_calc.py::test_param[a b]", timeout_s=60)
    assert r.kind == "verification"
    assert r.branch_id == result.witness.id and r.image_before == result.verification.image_after
    assert r.junit.collected == 1 and r.junit.passed == ["tests/test_calc.py::test_param[a b]"]


NEW_SPEC = "tests/test_new_feature.py::test_new_feature"


async def test_baseline_accepts_a_spec_test_whose_module_does_not_exist_yet(tmp_path):
    """A new-feature task: the failing test imports a module the fix will create, so
    collecting its file fails at baseline. That is a failing target, not a broken suite."""
    repo = make_repo(tmp_path / "src")
    (repo / "tests" / "test_new_feature.py").write_text(
        "from calc.feature import double\n\n\ndef test_new_feature():\n    assert double(2) == 4\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add spec test for a module that does not exist yet")
    ex = LocalExecutor(root=tmp_path / "work", sink=MemorySink(), run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))

    b = await establish_baseline(ex, base, "tests", [NEW_SPEC], limit_s=600)

    assert b.target == [NEW_SPEC]
    assert NEW_SPEC not in b.collected_ids
    assert "tests/test_calc.py::test_add" in b.protected
    assert all(run.collection_errors == ["tests/test_new_feature.py"] for run in b.runs)


async def test_patch_applies_to_a_witness_whose_files_have_crlf_line_endings(tmp_path):
    """Some SWE-rebench repositories keep CRLF files while git normalizes line endings on
    commit, so the extracted patch has LF lines. The witness must still take the patch, as
    the upstream grader does with its whitespace-tolerant apply flags."""
    repo = make_repo(tmp_path / "src")
    to_crlf = (
        "git config core.autocrlf input && python -c \"import pathlib; "
        "p = pathlib.Path('calc/__init__.py'); "
        "p.write_bytes(p.read_bytes().replace(b'\\\\n', b'\\\\r\\\\n'))\""
    )
    ex = LocalExecutor(root=tmp_path / "work", sink=MemorySink(), run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd=to_crlf))
    assert "\r\n" in await ex.read_file(base, "calc/__init__.py", 10_000)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    original = await ex.read_file(agent, "calc/__init__.py", 10_000)
    await ex.write_file(agent, "calc/__init__.py", original.replace("return a + b  # bug: should be a - b", "return a - b"))

    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)

    assert result.apply.exit_code == 0, result.apply.stdout_tail + result.apply.stderr_tail
    assert "tests/test_calc.py::test_sub" in result.verification.junit.passed
