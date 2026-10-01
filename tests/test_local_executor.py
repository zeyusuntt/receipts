import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from receipts.models import Receipt
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import RepoAtCommit
from receipts.sandbox.sink import MemorySink, RunSink
from tests.fixtures.repo_factory import make_repo


async def _executor(tmp_path, sink=None):
    repo = make_repo(tmp_path / "src")
    ex = LocalExecutor(root=tmp_path / "work", sink=sink or MemorySink(), run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))
    return ex, base


async def test_prepare_clones_and_runs_install(tmp_path):
    sink = MemorySink()
    ex, base = await _executor(tmp_path, sink)
    assert base.id == "base" and base.origin != base.head
    assert (ex.workdir(base) / "calc" / "__init__.py").exists()
    assert [r.kind for r in sink.receipts] == ["command"]
    assert sink.receipts[0].cmd == "true" and sink.receipts[0].exit_code == 0 and sink.receipts[0].seq == 1


async def test_prepare_fails_loudly_on_bad_install(tmp_path):
    import pytest
    repo = make_repo(tmp_path / "src")
    ex = LocalExecutor(root=tmp_path / "work", sink=MemorySink(), run_id="run-1")
    with pytest.raises(RuntimeError, match="install command failed"):
        await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="exit 7"))


async def test_run_records_receipt_and_advances_image(tmp_path):
    ex, base = await _executor(tmp_path)
    before = base.head
    r = await ex.run(base, "echo hello; echo err 1>&2; exit 3", timeout_s=10)
    assert r.kind == "command" and r.exit_code == 3
    assert r.stdout_tail == "hello\n" and r.stderr_tail == "err\n"
    assert r.image_before == before and r.image_after == base.head and r.image_after != before
    assert r.seq == 2 and r.receipt_id == "base-2"


async def test_run_timeout_kills_children(tmp_path):
    ex, base = await _executor(tmp_path)
    pidfile = tmp_path / "child.pid"
    r = await ex.run(base, f"sleep 30 & echo $! > {pidfile}; wait", timeout_s=1)
    assert r.timed_out is True and r.exit_code is None and r.duration_s < 5
    pid = int(pidfile.read_text().strip())
    for _ in range(20):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError(f"child {pid} still exists")


async def test_stdout_tail_is_capped_and_hashed_and_non_utf8_survives(tmp_path):
    ex, base = await _executor(tmp_path)
    r = await ex.run(base, "python -c \"import sys; sys.stdout.buffer.write(b'x' * 20000 + b'\\xff')\"", timeout_s=10)
    assert len(r.stdout_tail) == 6000 and r.stdout_sha256 is not None and r.exit_code == 0


async def test_write_and_read_file(tmp_path):
    ex, base = await _executor(tmp_path)
    r = await ex.write_file(base, "calc/new.py", "VALUE = 1\n")
    assert r.kind == "write" and r.path == "calc/new.py" and r.exit_code == 0
    assert await ex.read_file(base, "calc/new.py", max_bytes=100) == "VALUE = 1\n"
    assert await ex.read_file(base, "calc/__init__.py", max_bytes=5) == "def a"


async def test_write_outside_repo_is_refused(tmp_path):
    ex, base = await _executor(tmp_path)
    r = await ex.write_file(base, "../escape.py", "x")
    assert r.exit_code == 1 and "outside" in r.stderr_tail
    assert not (tmp_path / "work" / "escape.py").exists()


async def test_run_pytest_fills_junit_and_writes_it_complete(tmp_path):
    sink = MemorySink()
    ex, base = await _executor(tmp_path, sink)
    r = await ex.run_pytest(base, "tests", timeout_s=60, kind="verification")
    assert r.exit_code == 1 and r.kind == "verification"
    assert r.junit is not None and r.junit.collected == 4
    assert r.junit.failed == ["tests/test_calc.py::test_sub"]
    assert "tests/test_calc.py::test_param[a b]" in r.junit.passed
    written = sink.receipts[-1]
    assert written is r or written.model_dump() == r.model_dump()
    assert not any(p.suffix == ".xml" for p in ex.workdir(base).rglob("*"))


async def test_run_pytest_ignores_worktree_pytest_module(tmp_path):
    ex, base = await _executor(tmp_path)
    imported = tmp_path / "fake-pytest-imported"
    await ex.write_file(
        base,
        "pytest.py",
        f"from pathlib import Path\nPath({str(imported)!r}).write_text('imported')\n",
    )

    r = await ex.run_pytest(base, "tests", timeout_s=60)

    assert r.exit_code == 1 and r.junit is not None and r.junit.collected == 4
    assert not imported.exists()
    assert not any(path.suffix == ".pyc" for path in ex.workdir(base).rglob("*"))
    assert r.cmd.startswith("python -I ")


def test_pytest_bootstrap_rejects_untrusted_origin(tmp_path):
    fake_package = tmp_path / "fake-package"
    fake_package.mkdir()
    fake_pytest = fake_package / "pytest.py"
    fake_pytest.write_text("def main(args):\n    return 0\n")
    ex = LocalExecutor(root=tmp_path / "work", sink=MemorySink(), run_id="run-1")
    bootstrap = ex.root / "tools" / "receipts_pytest.py"

    completed = subprocess.run(
        [sys.executable, str(bootstrap)],
        cwd=fake_package,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(fake_package)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 4
    assert completed.stderr == f"receipts: untrusted pytest at {fake_pytest.resolve()}\n"


async def test_snapshot_then_patch_captures_modified_added_and_deleted_files(tmp_path):
    ex, base = await _executor(tmp_path)
    snapshot = await ex.snapshot(base)
    assert snapshot.kind == "command" and snapshot.exit_code == 0 and len(snapshot.snapshot_sha) == 40
    await ex.write_file(base, "calc/__init__.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    await ex.write_file(base, "calc/extra.py", "E = 1\n")
    await ex.run(base, "rm tests/test_calc.py", timeout_s=5)
    r = await ex.patch(base, snapshot.snapshot_sha)
    assert r.kind == "diff" and r.diff is not None and r.exit_code == 0
    assert sorted(f.path for f in r.diff.files) == ["calc/__init__.py", "calc/extra.py", "tests/test_calc.py"]
    by = {f.path: f for f in r.diff.files}
    assert by["calc/__init__.py"].added > 0 and by["calc/__init__.py"].deleted > 0
    assert by["calc/extra.py"].added == 1 and by["calc/extra.py"].deleted == 0
    assert by["tests/test_calc.py"].added == 0 and by["tests/test_calc.py"].deleted > 0
    assert Path(r.diff.patch_path).parent == ex.root / "patches"


async def test_patch_excludes_gitignored_file(tmp_path):
    ex, base = await _executor(tmp_path)
    snapshot = await ex.snapshot(base)
    await ex.write_file(base, "report.xml", "agent-controlled but ignored\n")
    r = await ex.patch(base, snapshot.snapshot_sha)
    assert r.exit_code == 0 and r.diff.files == []
    assert Path(r.diff.patch_path).read_text() == ""


async def test_patch_includes_untracked_non_ignored_file(tmp_path):
    ex, base = await _executor(tmp_path)
    snapshot = await ex.snapshot(base)
    await ex.write_file(base, "notes.txt", "new evidence\n")
    r = await ex.patch(base, snapshot.snapshot_sha)
    assert [(f.path, f.category) for f in r.diff.files] == [("notes.txt", "other")]
    assert "new file mode" in Path(r.diff.patch_path).read_text()


async def test_patch_then_apply_on_fresh_fork_reproduces_source(tmp_path):
    ex, base = await _executor(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    fixed = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    await ex.write_file(agent, "calc/__init__.py", fixed)
    patch = await ex.patch(agent, snapshot.snapshot_sha)
    patch_text = Path(patch.diff.patch_path).read_text()
    (witness,) = await ex.fork(c0, 1, prefix="w")
    applied = await ex.apply_patch(witness, patch_text)
    assert witness.id == "w1" and applied.kind == "apply" and applied.exit_code == 0
    assert applied.patch_sha256 == patch.diff.patch_sha256
    assert await ex.read_file(witness, "calc/__init__.py", 10_000) == fixed


async def test_apply_garbage_patch_fails_without_changing_tree(tmp_path):
    ex, base = await _executor(tmp_path)
    await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (witness,) = await ex.fork(c0, 1, prefix="w")
    before = await ex.read_file(witness, "calc/__init__.py", 10_000)
    applied = await ex.apply_patch(witness, "this is not a patch\n")
    after = await ex.read_file(witness, "calc/__init__.py", 10_000)
    status = subprocess.run(["git", "status", "--short"], cwd=ex.workdir(witness), capture_output=True, text=True, check=True)
    assert applied.exit_code != 0 and before == after and status.stdout == ""


async def test_fork_isolates_branches(tmp_path):
    ex, base = await _executor(tmp_path)
    c0 = await ex.checkpoint(base)
    b1, b2 = await ex.fork(c0, 2)
    assert {b1.id, b2.id} == {"b1", "b2"} and b1.origin == c0.id == b2.origin and b1.head == c0.id
    w1 = await ex.write_file(b1, "a.txt", "A")
    w2 = await ex.write_file(b2, "b.txt", "B")
    assert w1.seq == 1 and w2.seq == 1 and w1.receipt_id == "b1-1" and w2.receipt_id == "b2-1"
    assert w1.image_before == c0.id and w2.image_before == c0.id and w1.image_after != w2.image_after
    assert (ex.workdir(b1) / "a.txt").exists() and not (ex.workdir(b1) / "b.txt").exists()
    assert (ex.workdir(b2) / "b.txt").exists() and not (ex.workdir(b2) / "a.txt").exists()
    await ex.write_file(b1, "tests/test_calc.py", "def test_sub():\n    assert False\n")
    r1 = await ex.run_pytest(b1, "tests", timeout_s=60)
    r2 = await ex.run_pytest(b2, "tests", timeout_s=60)
    assert r1.junit.collected == 1 and r2.junit.collected == 4
    assert not (ex.workdir(base) / "a.txt").exists()
    witness1, witness2 = await ex.fork(c0, 2, prefix="w")
    assert [witness1.id, witness2.id] == ["w1", "w2"]


async def test_run_sink_routes_by_branch(tmp_path):
    run_dir = tmp_path / "run"
    ex, base = await _executor(tmp_path, RunSink(run_dir))
    c0 = await ex.checkpoint(base)
    b1, b2 = await ex.fork(c0, 2)
    await ex.run(b1, "true", timeout_s=5)
    await ex.run(b2, "false", timeout_s=5)
    await ex.run(b1, "true", timeout_s=5)
    lines1 = (run_dir / "branches" / "b1" / "receipts.jsonl").read_text().splitlines()
    lines2 = (run_dir / "branches" / "b2" / "receipts.jsonl").read_text().splitlines()
    assert [Receipt.model_validate_json(l).seq for l in lines1] == [1, 2]
    assert [json.loads(l)["branch_id"] for l in lines2] == ["b2"]
    assert (run_dir / "branches" / "base" / "receipts.jsonl").exists()
