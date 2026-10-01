import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import receipts.sandbox.local as local_sandbox
from receipts.models import Receipt
from receipts.sandbox.local import CheckpointTampered, LocalExecutor
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


async def test_run_persists_full_stdout_log_outside_worktree(tmp_path):
    ex, base = await _executor(tmp_path)
    expected = b"x" * 7000 + b"\xff"

    r = await ex.run(
        base,
        "python -c \"import sys; sys.stdout.buffer.write(b'x' * 7000 + b'\\xff')\"",
        timeout_s=10,
    )

    assert r.log_path is not None
    assert Path(r.log_path).read_bytes() == expected
    assert Path(r.log_path).parent == ex.root / "logs"
    assert ex.workdir(base) not in Path(r.log_path).parents


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


async def test_run_pytest_persists_full_stdout_log(tmp_path):
    ex, base = await _executor(tmp_path)

    r = await ex.run_pytest(base, "tests", timeout_s=60)

    assert r.log_path is not None
    log_path = Path(r.log_path)
    assert log_path.parent == ex.root / "logs"
    assert log_path.read_bytes().endswith(r.stdout_tail.encode())
    assert b"test_sub" in log_path.read_bytes()


async def test_tree_digest_tracks_worktree_changes_and_ignores_git_metadata(tmp_path):
    ex, base = await _executor(tmp_path)

    tested = await ex.run_pytest(base, "tests", timeout_s=60)
    read_only = await ex.run(base, "cat calc/__init__.py >/dev/null", timeout_s=10)
    changed = await ex.write_file(base, "calc/new.py", "VALUE = 1\n")
    git_only = await ex.run(base, "printf metadata > .git/claim-audit-probe", timeout_s=10)

    assert tested.tree_digest is not None
    assert read_only.tree_digest == tested.tree_digest
    assert changed.tree_digest != tested.tree_digest
    assert git_only.tree_digest == changed.tree_digest


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


async def test_patch_ignores_agent_external_diff_config(tmp_path):
    ex, base = await _executor(tmp_path)
    snapshot = await ex.snapshot(base)
    checkpoint = await ex.checkpoint(base)
    (agent,) = await ex.fork(checkpoint, 1)
    await ex.write_file(agent, "fake-diff.sh", "#!/bin/sh\nexit 99\n")
    await ex.write_file(agent, "notes.txt", "real patch content\n")
    configured = await ex.run(
        agent,
        "chmod +x fake-diff.sh && git config diff.external ./fake-diff.sh",
        timeout_s=30,
    )
    assert configured.exit_code == 0

    receipt = await ex.patch(agent, snapshot.snapshot_sha)

    assert receipt.exit_code == 0 and receipt.diff is not None
    assert {item.path for item in receipt.diff.files} == {"fake-diff.sh", "notes.txt"}
    assert "real patch content" in Path(receipt.diff.patch_path).read_text()
    assert "staging" in receipt.cmd


async def test_patch_ignores_agent_clean_filter_config(tmp_path):
    ex, base = await _executor(tmp_path)
    snapshot = await ex.snapshot(base)
    checkpoint = await ex.checkpoint(base)
    (agent,) = await ex.fork(checkpoint, 1)
    await ex.write_file(agent, ".gitattributes", "calc/__init__.py filter=poison\n")
    await ex.write_file(agent, "poison-filter.sh", "#!/bin/sh\nprintf 'FILTERED\\n'\n")
    configured = await ex.run(
        agent,
        "chmod +x poison-filter.sh && git config filter.poison.clean ./poison-filter.sh",
        timeout_s=30,
    )
    assert configured.exit_code == 0
    await ex.write_file(
        agent,
        "calc/__init__.py",
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n",
    )

    receipt = await ex.patch(agent, snapshot.snapshot_sha)
    patch_text = Path(receipt.diff.patch_path).read_text()

    assert receipt.exit_code == 0
    assert "+    return a - b" in patch_text
    assert "\n+FILTERED\n" not in patch_text


async def test_patch_does_not_run_worktree_git_executable(tmp_path):
    ex, base = await _executor(tmp_path)
    snapshot = await ex.snapshot(base)
    checkpoint = await ex.checkpoint(base)
    (agent,) = await ex.fork(checkpoint, 1)
    marker = tmp_path / "worktree-git-ran"
    await ex.write_file(
        agent,
        ".venv/bin/git",
        f"#!/bin/sh\nprintf ran > {str(marker)!r}\nexit 73\n",
    )
    made_executable = await ex.run(agent, "chmod +x .venv/bin/git", timeout_s=30)
    assert made_executable.exit_code == 0
    await ex.write_file(agent, "notes.txt", "real patch content\n")

    receipt = await ex.patch(agent, snapshot.snapshot_sha)

    assert receipt.exit_code == 0
    assert not marker.exists()
    assert "real patch content" in Path(receipt.diff.patch_path).read_text()


async def test_patch_does_not_run_worktree_bash_executable(tmp_path):
    ex, base = await _executor(tmp_path)
    snapshot = await ex.snapshot(base)
    checkpoint = await ex.checkpoint(base)
    (agent,) = await ex.fork(checkpoint, 1)
    marker = tmp_path / "worktree-bash-ran"
    await ex.write_file(
        agent,
        ".venv/bin/bash",
        "#!/bin/sh\n"
        f"printf ran > {str(marker)!r}\n"
        "printf '%s\\n' "
        "'diff --git a/forged.txt b/forged.txt' "
        "'new file mode 100644' "
        "'index 0000000..ce01362' "
        "'--- /dev/null' "
        "'+++ b/forged.txt' "
        "'@@ -0,0 +1 @@' "
        "'+forged'\n",
    )
    (ex.workdir(agent) / ".venv/bin/bash").chmod(0o755)
    await ex.write_file(agent, "notes.txt", "real patch content\n")

    receipt = await ex.patch(agent, snapshot.snapshot_sha)

    assert receipt.exit_code == 0 and receipt.diff is not None
    assert not marker.exists()
    assert {item.path for item in receipt.diff.files} == {".venv/bin/bash", "notes.txt"}
    assert "real patch content" in Path(receipt.diff.patch_path).read_text()


async def test_patch_disables_rename_detection(tmp_path):
    ex, base = await _executor(tmp_path)
    snapshot = await ex.snapshot(base)
    checkpoint = await ex.checkpoint(base)
    (agent,) = await ex.fork(checkpoint, 1)
    moved = await ex.run(agent, "git mv tests/test_calc.py calc/hidden_test_copy.txt", timeout_s=30)
    assert moved.exit_code == 0

    receipt = await ex.patch(agent, snapshot.snapshot_sha)

    assert receipt.exit_code == 0 and receipt.diff is not None
    assert [(item.path, item.added, item.deleted) for item in receipt.diff.files] == [
        ("calc/hidden_test_copy.txt", 20, 0),
        ("tests/test_calc.py", 0, 20),
    ]
    assert "similarity index" not in Path(receipt.diff.patch_path).read_text()


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


async def test_checkpoint_digest_is_stable_for_identical_copies(tmp_path):
    ex, base = await _executor(tmp_path)

    first = await ex.checkpoint(base)
    second = await ex.checkpoint(base)

    assert first.digest is not None and len(first.digest) == 64
    assert second.digest == first.digest


def test_checkpoint_digest_handles_surrogateescaped_path():
    undecodable = os.fsdecode(b"invalid-\xff.py")

    digest = local_sandbox._checkpoint_manifest_digest([(undecodable, 0o100644, "abc")])

    assert len(digest) == 64


async def test_fork_rejects_checkpoint_modified_from_agent_branch(tmp_path):
    ex, base = await _executor(tmp_path)
    checkpoint = await ex.checkpoint(base)
    (agent,) = await ex.fork(checkpoint, 1)
    escaped = await ex.run(
        agent,
        "python -c \"from pathlib import Path; p=next(Path('..').glob('ckpt-*/tests/test_calc.py')); p.write_text('tampered\\n')\"",
        timeout_s=30,
    )
    assert escaped.exit_code == 0

    with pytest.raises(CheckpointTampered) as error:
        await ex.fork(checkpoint, 1, prefix="w")

    assert error.value.checkpoint_id == checkpoint.id


async def test_patch_rejects_tampered_origin_checkpoint(tmp_path):
    ex, base = await _executor(tmp_path)
    snapshot = await ex.snapshot(base)
    checkpoint = await ex.checkpoint(base)
    (agent,) = await ex.fork(checkpoint, 1)
    escaped = await ex.run(
        agent,
        "python -c \"from pathlib import Path; p=next(Path('..').glob('ckpt-*/calc/__init__.py')); p.chmod(0o755)\"",
        timeout_s=30,
    )
    assert escaped.exit_code == 0

    with pytest.raises(CheckpointTampered) as error:
        await ex.patch(agent, snapshot.snapshot_sha)

    assert error.value.checkpoint_id == checkpoint.id


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


async def test_release_removes_branch_but_preserves_checkpoint_and_refuses_run(tmp_path):
    ex, base = await _executor(tmp_path)
    checkpoint = await ex.checkpoint(base)
    (agent,) = await ex.fork(checkpoint, 1)
    branch_dir = ex.workdir(agent)
    checkpoint_dir = ex._dirs[checkpoint.id]

    await ex.release(agent)
    await ex.release(agent)

    assert not branch_dir.exists()
    assert checkpoint_dir.is_dir()
    with pytest.raises(RuntimeError, match="released Local branch: b1"):
        await ex.run(agent, "true", timeout_s=5)


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


async def test_run_pytest_reports_invocation_relative_ids_when_the_rootdir_is_nested(tmp_path):
    import subprocess

    from receipts.sandbox.local import LocalExecutor
    from receipts.sandbox.protocol import RepoAtCommit
    from receipts.sandbox.sink import MemorySink

    repo = tmp_path / "nested"
    (repo / "pkg" / "tests").mkdir(parents=True)
    (repo / "pkg" / "setup.cfg").write_text("[tool:pytest]\naddopts =\n")
    (repo / "pkg" / "tests" / "test_k.py").write_text("def test_a():\n    assert True\n")
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=f@x", "-c", "user.name=f", "commit", "-q", "-m", "nested"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    ex = LocalExecutor(root=tmp_path / "work", sink=MemorySink(), run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))

    receipt = await ex.run_pytest(base, "pkg/tests/test_k.py", timeout_s=120)

    assert receipt.exit_code == 0
    assert receipt.junit.passed == ["pkg/tests/test_k.py::test_a"]


async def test_local_command_duration_ignores_wall_clock_jumps(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import receipts.sandbox.local as local_module
    from receipts.sandbox.local import LocalExecutor
    from receipts.sandbox.protocol import RepoAtCommit
    from receipts.sandbox.sink import MemorySink
    from tests.fixtures.repo_factory import make_repo

    repo = make_repo(tmp_path / "src")
    ex = LocalExecutor(root=tmp_path / "work", sink=MemorySink(), run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    ticks = iter([start, start + timedelta(seconds=1000)] * 10)
    monkeypatch.setattr(local_module, "_now", lambda: next(ticks))

    receipt = await ex.run(base, "true", timeout_s=30)

    assert receipt.duration_s < 60


async def test_trusted_runner_import_path_matches_the_plain_pytest_command(tmp_path):
    """The official grader runs the instance's `pytest` command, which does not put the
    repository root on sys.path. If the trusted runner did, a new top-level package in a
    patch could shadow the installed one and pass the gate while failing the grader."""
    import os
    import subprocess
    import sys

    from receipts.sandbox.local import LocalExecutor
    from receipts.sandbox.protocol import RepoAtCommit
    from receipts.sandbox.sink import MemorySink

    repo = tmp_path / "rootpath"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_path.py").write_text(
        "import os, sys\n\n\n"
        "def test_repository_root_is_not_importable():\n"
        "    root = os.path.realpath(os.getcwd())\n"
        "    assert root not in {os.path.realpath(p or os.getcwd()) for p in sys.path}\n"
    )
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=f@x", "-c", "user.name=f", "commit", "-q", "-m", "path"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    plain = subprocess.run(
        [os.path.join(os.path.dirname(sys.executable), "pytest"), "-q", "-p", "no:cacheprovider", "tests/test_path.py"],
        cwd=repo, capture_output=True, text=True,
    )
    assert plain.returncode == 0, plain.stdout
    ex = LocalExecutor(root=tmp_path / "work", sink=MemorySink(), run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))

    receipt = await ex.run_pytest(base, "tests/test_path.py", timeout_s=120)

    assert receipt.exit_code == 0
    assert receipt.junit.passed == ["tests/test_path.py::test_repository_root_is_not_importable"]


async def test_apply_patch_tolerates_line_ending_differences_like_the_upstream_grader(tmp_path):
    """Observed on pennylane-2834: the file is CRLF on disk, the extracted patch is LF.
    SWE-rebench-V2's grader applies with --ignore-space-change and takes such a patch."""
    import subprocess

    from receipts.sandbox.local import LocalExecutor
    from receipts.sandbox.protocol import RepoAtCommit
    from receipts.sandbox.sink import MemorySink

    repo = tmp_path / "crlf"
    (repo / "calc").mkdir(parents=True)
    (repo / "calc" / "__init__.py").write_bytes(
        b"def add(a, b):\r\n    return a + b\r\n\r\n\r\ndef sub(a, b):\r\n    return a + b  # bug\r\n"
    )
    for args in (["init", "-q"], ["config", "core.autocrlf", "false"], ["add", "-A"],
                 ["-c", "user.email=f@x", "-c", "user.name=f", "commit", "-q", "-m", "crlf"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    ex = LocalExecutor(root=tmp_path / "work", sink=MemorySink(), run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))
    await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (witness,) = await ex.fork(c0, 1, prefix="w")
    lf_patch = (
        "diff --git a/calc/__init__.py b/calc/__init__.py\n"
        "--- a/calc/__init__.py\n"
        "+++ b/calc/__init__.py\n"
        "@@ -5,2 +5,2 @@\n"
        " def sub(a, b):\n"
        "-    return a + b  # bug\n"
        "+    return a - b\n"
    )

    receipt = await ex.apply_patch(witness, lf_patch)

    assert receipt.exit_code == 0, receipt.stdout_tail + receipt.stderr_tail
    assert "return a - b" in await ex.read_file(witness, "calc/__init__.py", 10_000)
