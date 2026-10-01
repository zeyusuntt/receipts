import asyncio
import hashlib
import importlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

import pytest

from receipts.sandbox import protocol
from receipts.models import Branch, Receipt
from receipts.sandbox.local import CheckpointTampered as LocalCheckpointTampered
from receipts.sandbox.sink import MemorySink, RunSink
from tests.fixtures.repo_factory import make_repo


TEST_IMAGE = "receipts-test-base:py312"
SHA256_IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _docker_available() -> bool:
    try:
        completed = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


requires_docker = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon is not reachable",
)


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        check=check,
        timeout=60,
    )


def _run_id() -> str:
    return f"receipts-{uuid.uuid4().hex[:12]}"


def _tar_bytes(root: Path) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            archive.add(path, arcname=path.name, recursive=True)
    return output.getvalue()


def test_image_source_has_independent_setup_lists():
    image_source = getattr(protocol, "ImageSource")
    first = image_source(image="example:latest", workdir="/workspace")
    second = image_source(image="example:latest", workdir="/workspace")

    first.setup.append("true")

    assert second.setup == []
    assert first.python == "python"
    assert first.platform is None


def test_checkpoint_tampered_lives_in_protocol_and_is_reexported():
    protocol_error = getattr(protocol, "CheckpointTampered")

    assert LocalCheckpointTampered is protocol_error


@pytest.mark.docker
@requires_docker
async def test_prepare_image_source_runs_setup_and_initializes_git(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    sink = MemorySink()
    run_id = _run_id()
    source = protocol.ImageSource(
        image=TEST_IMAGE,
        workdir="/workspace",
        setup=["printf setup > setup.txt"],
    )

    async with docker_module.DockerExecutor(tmp_path / "executor", sink, run_id) as executor:
        base = await executor.prepare(source)

        assert base.id == "base"
        assert SHA256_IMAGE.fullmatch(base.head)
        assert await executor.read_file(base, "setup.txt", 100) == "setup"
        assert (await executor.read_file(base, ".git/HEAD", 100)).startswith("ref:")
        assert [receipt.exit_code for receipt in sink.receipts] == [0, 0]
        assert sink.receipts[0].cmd == "printf setup > setup.txt"
        assert "git init -q" in sink.receipts[1].cmd
        assert all(SHA256_IMAGE.fullmatch(receipt.image_after) for receipt in sink.receipts)


@pytest.mark.docker
@requires_docker
async def test_prepare_repo_at_commit_clones_and_runs_install(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    repo = make_repo(tmp_path / "source")
    staging_name = f"fixture-{uuid.uuid4().hex[:12]}"
    _docker("create", "--name", staging_name, TEST_IMAGE)
    try:
        _docker("start", staging_name)
        _docker("exec", staging_name, "mkdir", "-p", "/fixture-repo")
        _docker("cp", f"{repo}/.", f"{staging_name}:/fixture-repo")
        _docker(
            "exec",
            "-u",
            "0",
            staging_name,
            "chown",
            "-R",
            "0:0",
            "/fixture-repo",
        )
        fixture_image = _docker("commit", staging_name).stdout.strip()
    finally:
        _docker("rm", "-f", staging_name, check=False)

    executor = docker_module.DockerExecutor(
        tmp_path / "executor",
        MemorySink(),
        _run_id(),
        base_image=fixture_image,
    )
    try:
        base = await executor.prepare(
            protocol.RepoAtCommit(
                url="/fixture-repo",
                commit="HEAD",
                install_cmd="printf installed > installed.txt",
            ),
        )

        assert "def add" in await executor.read_file(base, "calc/__init__.py", 1_000)
        assert await executor.read_file(base, "installed.txt", 100) == "installed"
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_prepare_fails_loudly_on_bad_setup(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())

    try:
        with pytest.raises(RuntimeError, match="setup command failed"):
            await executor.prepare(
                protocol.ImageSource(
                    image=TEST_IMAGE,
                    workdir="/workspace",
                    setup=["exit 7"],
                ),
            )
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_prepare_overrides_image_entrypoint(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    staging_name = f"fixture-{uuid.uuid4().hex[:12]}"
    _docker("create", "--name", staging_name, TEST_IMAGE)
    try:
        entrypoint_image = _docker(
            "commit",
            "--change",
            'ENTRYPOINT ["false"]',
            staging_name,
        ).stdout.strip()
    finally:
        _docker("rm", "-f", staging_name, check=False)

    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=entrypoint_image, workdir="/workspace"),
        )

        assert (await executor.run(base, "true", 10)).exit_code == 0
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_prepare_rejects_image_volumes_that_commit_would_omit(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    staging_name = f"fixture-{uuid.uuid4().hex[:12]}"
    _docker("create", "--name", staging_name, TEST_IMAGE)
    try:
        volume_image = _docker(
            "commit",
            "--change",
            "VOLUME /workspace",
            staging_name,
        ).stdout.strip()
    finally:
        _docker("rm", "-f", staging_name, check=False)

    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())
    try:
        with pytest.raises(ValueError, match="volume"):
            await executor.prepare(
                protocol.ImageSource(image=volume_image, workdir="/workspace"),
            )
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_run_and_write_advance_sha256_images(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    sink = MemorySink()
    executor = docker_module.DockerExecutor(tmp_path / "executor", sink, _run_id())
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )
        before_run = base.head

        command = await executor.run(base, "printf hello; printf err >&2; exit 3", 10)
        before_write = base.head
        written = await executor.write_file(base, "pkg/new.py", "VALUE = 1\n")
        read_only = await executor.run(base, "cat pkg/new.py >/dev/null", 10)

        assert command.exit_code == 3
        assert command.stdout_tail == "hello" and command.stderr_tail == "err"
        assert command.image_before == before_run
        assert command.image_after == before_write
        assert command.image_after != before_run
        assert SHA256_IMAGE.fullmatch(command.image_after)
        assert written.image_before == before_write
        assert written.image_after == read_only.image_before
        assert written.image_after != before_write
        assert SHA256_IMAGE.fullmatch(written.image_after)
        assert read_only.image_after == base.head
        assert command.tree_digest is not None
        assert written.tree_digest != command.tree_digest
        assert read_only.tree_digest == written.tree_digest
        assert await executor.read_file(base, "pkg/new.py", 5) == "VALUE"
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_stdout_tail_is_capped_hashed_and_non_utf8_safe(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )

        receipt = await executor.run(
            base,
            "python -c \"import sys; sys.stdout.buffer.write(b'x' * 20000 + b'\\xff')\"",
            10,
        )

        assert receipt.exit_code == 0
        assert len(receipt.stdout_tail) == 6000
        assert receipt.stdout_sha256 is not None
        assert receipt.stdout_tail.endswith("�")
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_run_pytest_uses_trusted_runner_and_advances_image(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )
        await executor.write_file(
            base,
            "tests/test_sample.py",
            "def test_ok():\n    assert True\n\ndef test_bad():\n    assert False\n",
        )
        await executor.write_file(base, "pytest.py", "raise RuntimeError('untrusted pytest imported')\n")
        before = base.head

        receipt = await executor.run_pytest(
            base,
            "tests",
            timeout_s=60,
            kind="verification",
        )

        assert receipt.exit_code == 1 and receipt.kind == "verification"
        assert receipt.junit is not None
        assert receipt.junit.passed == ["tests/test_sample.py::test_ok"]
        assert receipt.junit.failed == ["tests/test_sample.py::test_bad"]
        assert receipt.image_before == before
        assert receipt.image_after == base.head and receipt.image_after != before
        assert SHA256_IMAGE.fullmatch(receipt.image_after)
        assert receipt.log_path is not None
        assert b"test_bad" in Path(receipt.log_path).read_bytes()
        assert not await executor.read_file(base, "__pycache__/pytest.pyc", 100)
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_patch_ignores_hostile_git_config_and_apply_reproduces_tree(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )
        await executor.write_file(base, "calc.py", "VALUE = 1\n")
        await executor.write_file(base, "doomed.py", "DELETE = True\n")
        await executor.write_file(base, ".gitignore", "ignored.log\n")
        snapshot = await executor.snapshot(base)
        checkpoint = await executor.checkpoint(base)
        (agent,) = await executor.fork(checkpoint, 1)
        await executor.write_file(agent, "calc.py", "VALUE = 2\n")
        await executor.write_file(agent, "ignored.log", "not evidence\n")
        await executor.write_file(
            agent,
            "fake-diff.sh",
            "#!/bin/sh\nprintf ran > /tmp/receipts-fake-diff-ran\nexit 99\n",
        )
        configured = await executor.run(
            agent,
            "rm doomed.py && chmod +x fake-diff.sh && git config diff.external ./fake-diff.sh",
            30,
        )
        assert configured.exit_code == 0
        before_patch = agent.head

        patch_receipt = await executor.patch(agent, snapshot.snapshot_sha)

        assert patch_receipt.exit_code == 0 and patch_receipt.diff is not None
        assert {item.path for item in patch_receipt.diff.files} == {
            "calc.py",
            "doomed.py",
            "fake-diff.sh",
        }
        patch_text = Path(patch_receipt.diff.patch_path).read_text()
        assert "+VALUE = 2" in patch_text
        assert patch_receipt.image_before == patch_receipt.image_after == before_patch
        marker_absent = await executor.run(agent, "test ! -e /tmp/receipts-fake-diff-ran", 10)
        assert marker_absent.exit_code == 0

        (witness,) = await executor.fork(checkpoint, 1, prefix="w")
        before_apply = witness.head
        applied = await executor.apply_patch(witness, patch_text)

        assert applied.exit_code == 0 and applied.kind == "apply"
        assert applied.patch_sha256 == patch_receipt.diff.patch_sha256
        assert applied.image_before == before_apply
        assert applied.image_after == witness.head and applied.image_after != before_apply
        assert SHA256_IMAGE.fullmatch(applied.image_after)
        assert await executor.read_file(witness, "calc.py", 100) == "VALUE = 2\n"
        assert await executor.read_file(witness, "doomed.py", 100) == ""
        before_empty = witness.head
        empty = await executor.apply_patch(witness, "")
        assert empty.exit_code == 0
        assert empty.patch_sha256 == hashlib.sha256(b"").hexdigest()
        assert empty.image_before == before_empty
        assert empty.image_after == witness.head and empty.image_after != before_empty
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_apply_garbage_patch_fails_without_changing_worktree(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )
        await executor.write_file(base, "calc.py", "VALUE = 1\n")
        await executor.snapshot(base)
        checkpoint = await executor.checkpoint(base)
        (witness,) = await executor.fork(checkpoint, 1, prefix="w")
        before = await executor.read_file(witness, "calc.py", 100)

        applied = await executor.apply_patch(witness, "this is not a patch\n")

        assert applied.exit_code != 0
        assert await executor.read_file(witness, "calc.py", 100) == before
        clean = await executor.run(witness, "test -z \"$(git status --short)\"", 10)
        assert clean.exit_code == 0
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_file_paths_are_confined_to_workdir_including_symlinks(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )
        await executor.run(
            base,
            "printf secret > /tmp/receipts-secret && ln -s /tmp/receipts-secret secret-link && ln -s /tmp escape",
            10,
        )

        parent_escape = await executor.write_file(base, "../escape.py", "x")
        absolute_escape = await executor.write_file(base, "/tmp/escape.py", "x")
        symlink_escape = await executor.write_file(base, "escape/escape.py", "x")

        assert parent_escape.exit_code == 1
        assert absolute_escape.exit_code == 1
        assert symlink_escape.exit_code == 1
        assert "outside" in symlink_escape.stderr_tail
        assert await executor.read_file(base, "secret-link", 100) == ""
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_file_write_rejects_retargeted_workdir(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )
        retargeted = await executor.run(
            base,
            "mv /workspace /moved-workspace && ln -s / /workspace",
            10,
        )

        escaped = await executor.write_file(base, "tmp/receipts-escape", "escaped")

        assert retargeted.exit_code == 0
        assert escaped.exit_code == 1
        assert "outside" in escaped.stderr_tail
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_snapshot_checkpoint_and_forks_are_isolated(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    run_id = _run_id()
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), run_id)
    try:
        base = await executor.prepare(
            protocol.ImageSource(
                image=TEST_IMAGE,
                workdir="/workspace",
                setup=["printf base > base.txt"],
            ),
        )
        before_snapshot = base.head
        snapshot = await executor.snapshot(base)
        checkpoint = await executor.checkpoint(base)
        first, second = await executor.fork(checkpoint, 2)
        first_write = await executor.write_file(first, "only-first.txt", "first")
        (third,) = await executor.fork(checkpoint, 1)

        assert snapshot.exit_code == 0 and snapshot.snapshot_sha is not None
        assert len(snapshot.snapshot_sha) == 40
        assert snapshot.image_before == before_snapshot
        assert snapshot.image_after == base.head
        assert snapshot.image_after != before_snapshot
        assert checkpoint.id == checkpoint.digest
        assert SHA256_IMAGE.fullmatch(checkpoint.id)
        assert [first.id, second.id, third.id] == ["b1", "b2", "b3"]
        assert first.origin == checkpoint.id == second.origin == third.origin
        assert first_write.image_after == first.head
        assert await executor.read_file(first, "only-first.txt", 100) == "first"
        assert await executor.read_file(second, "only-first.txt", 100) == ""
        assert await executor.read_file(third, "only-first.txt", 100) == ""
        inspected = _docker("inspect", "--format", "{{.Name}}", f"{run_id}-b1")
        assert inspected.stdout.strip() == f"/{run_id}-b1"
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_timeout_records_timeout_and_container_remains_usable(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )

        timed_out = await executor.run(base, "sleep 30", 1)
        after = await executor.run(base, "printf alive", 10)

        assert timed_out.timed_out is True
        assert timed_out.exit_code is None
        assert timed_out.duration_s < 10
        assert after.exit_code == 0 and after.stdout_tail == "alive"
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_run_kills_detached_children_before_committing(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), _run_id())
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )
        command = (
            "python -c \"import os,time; os.setsid(); time.sleep(2); "
            "open('/workspace/late.txt','w').write('late')\" >/dev/null 2>&1 &"
        )

        receipt = await executor.run(base, command, 10)
        await asyncio.sleep(3)

        assert receipt.exit_code == 0
        assert await executor.read_file(base, "late.txt", 100) == ""
    finally:
        await executor.close()


@pytest.mark.docker
@requires_docker
async def test_async_context_manager_removes_every_created_container(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    run_id = _run_id()
    executor = docker_module.DockerExecutor(tmp_path / "executor", MemorySink(), run_id)

    async with executor:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )
        checkpoint = await executor.checkpoint(base)
        await executor.fork(checkpoint, 2)

    for branch_id in ("base", "b1", "b2"):
        inspected = _docker("inspect", f"{run_id}-{branch_id}", check=False)
        assert inspected.returncode != 0


@pytest.mark.docker
@requires_docker
async def test_run_sink_routes_receipts_by_fork(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    run_dir = tmp_path / "run"
    executor = docker_module.DockerExecutor(
        tmp_path / "executor",
        RunSink(run_dir),
        _run_id(),
    )
    try:
        base = await executor.prepare(
            protocol.ImageSource(image=TEST_IMAGE, workdir="/workspace"),
        )
        checkpoint = await executor.checkpoint(base)
        first, second = await executor.fork(checkpoint, 2)

        await executor.run(first, "true", 5)
        await executor.run(second, "false", 5)
        await executor.run(first, "true", 5)

        first_lines = (run_dir / "branches" / "b1" / "receipts.jsonl").read_text().splitlines()
        second_lines = (run_dir / "branches" / "b2" / "receipts.jsonl").read_text().splitlines()
        assert [Receipt.model_validate_json(line).seq for line in first_lines] == [1, 2]
        assert [json.loads(line)["branch_id"] for line in second_lines] == ["b2"]
        assert (run_dir / "branches" / "base" / "receipts.jsonl").exists()
    finally:
        await executor.close()


async def test_close_retains_failed_container_for_retry(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")

    class RetryCloseExecutor(docker_module.DockerExecutor):
        def __init__(self):
            super().__init__(tmp_path / "executor", MemorySink(), "retry-close")
            self._created_containers = ["retry-close-base"]
            self.remove_attempts = 0

        async def _docker(self, *args, **kwargs):
            self.remove_attempts += 1
            code = 1 if self.remove_attempts == 1 else 0
            stderr = b"temporary failure" if code else b""
            return b"", stderr, code, False, None, 0.0

    executor = RetryCloseExecutor()

    with pytest.raises(RuntimeError, match="failed to remove"):
        await executor.close()
    assert executor._created_containers == ["retry-close-base"]

    await executor.close()

    assert executor.remove_attempts == 2
    assert executor._created_containers == []


async def test_run_persists_full_stdout_log_without_a_docker_daemon(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    expected = b"x" * 7000 + b"\xff"

    class FakeRunExecutor(docker_module.DockerExecutor):
        async def _execute(self, branch, cmd, timeout_s):
            return expected, b"", 0, False, docker_module._now(), 0.1

        async def _commit(self, container):
            return "sha256:" + "1" * 64

        async def _tree_digest(self, branch):
            return "a" * 64

    executor = FakeRunExecutor(tmp_path / "executor", MemorySink(), "offline-run")
    branch = Branch(
        id="b1",
        run_id="offline-run",
        head="sha256:" + "0" * 64,
        origin="sha256:" + "0" * 64,
    )
    executor._containers[branch.id] = "offline-run-b1"

    receipt = await executor.run(branch, "print output", 10)

    assert receipt.log_path is not None
    assert (tmp_path / "executor" / "logs" / "b1-1.log").read_bytes() == expected
    assert receipt.log_path == str(tmp_path / "executor" / "logs" / "b1-1.log")
    assert receipt.stdout_tail.endswith("�")
    assert receipt.tree_digest == "a" * 64


async def test_run_pytest_reads_junit_logs_stdout_and_advances_image_offline(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    junit_xml = tmp_path / "junit.xml"
    junit_xml.write_text(
        '<?xml version="1.0"?><testsuites><testsuite>'
        '<testcase classname="tests.test_sample" name="test_ok" '
        'file="tests/test_sample.py" />'
        '</testsuite></testsuites>',
    )
    stdout = b"tests/test_sample.py::test_ok PASSED\n"

    class FakePytestExecutor(docker_module.DockerExecutor):
        def __init__(self):
            super().__init__(tmp_path / "executor", MemorySink(), "offline-pytest")
            self.command = ""
            self.environment = None

        async def _execute(self, branch, cmd, timeout_s, env_overrides=None):
            self.command = cmd
            self.environment = env_overrides
            return stdout, b"", 0, False, docker_module._now(), 0.1

        async def _docker(self, *args, **kwargs):
            return junit_xml.read_bytes(), b"", 0, False, docker_module._now(), 0.1

        async def _commit(self, container):
            return "sha256:" + "2" * 64

        async def _tree_digest(self, branch):
            return "b" * 64

    executor = FakePytestExecutor()
    branch = Branch(
        id="b1",
        run_id="offline-pytest",
        head="sha256:" + "1" * 64,
        origin="sha256:" + "0" * 64,
    )
    executor._containers[branch.id] = "offline-pytest-b1"
    executor._specs[branch.id] = docker_module._ContainerSpec("/workspace", "python", None)

    receipt = await executor.run_pytest(
        branch,
        "tests",
        timeout_s=60,
        kind="verification",
    )

    assert executor.command == (
        "python -I /opt/receipts/receipts_pytest.py tests "
        "--junitxml=/opt/receipts/reports/b1-1.xml "
        "-o junit_family=xunit1 -p no:cacheprovider -rA"
    )
    assert executor.environment == {"PYTEST_ADDOPTS": "", "PYTEST_PLUGINS": ""}
    assert receipt.kind == "verification" and receipt.exit_code == 0
    assert receipt.junit is not None
    assert receipt.junit.passed == ["tests/test_sample.py::test_ok"]
    assert receipt.image_after == branch.head == "sha256:" + "2" * 64
    assert receipt.log_path is not None
    assert Path(receipt.log_path).read_bytes() == stdout
    assert receipt.tree_digest == "b" * 64


async def test_run_pytest_rejects_stale_host_junit_when_container_report_is_missing(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")

    class MissingReportExecutor(docker_module.DockerExecutor):
        async def _execute(self, branch, cmd, timeout_s, env_overrides=None):
            return b"pytest failed before collection\n", b"", 4, False, docker_module._now(), 0.1

        async def _docker(self, *args, **kwargs):
            return b"", b"missing", 1, False, docker_module._now(), 0.1

        async def _commit(self, container):
            return "sha256:" + "2" * 64

        async def _tree_digest(self, branch):
            return "c" * 64

    executor = MissingReportExecutor(tmp_path / "executor", MemorySink(), "stale-junit")
    stale_report = tmp_path / "executor" / "reports" / "b1-1.xml"
    stale_report.write_text(
        '<?xml version="1.0"?><testsuites><testsuite>'
        '<testcase classname="tests.test_stale" name="test_fake" file="tests/test_stale.py" />'
        '</testsuite></testsuites>',
    )
    branch = Branch(
        id="b1",
        run_id="stale-junit",
        head="sha256:" + "1" * 64,
        origin="sha256:" + "0" * 64,
    )
    executor._containers[branch.id] = "stale-junit-b1"
    executor._specs[branch.id] = docker_module._ContainerSpec("/workspace", "python", None)

    receipt = await executor.run_pytest(branch, "tests", timeout_s=60)

    assert receipt.exit_code == 4
    assert receipt.junit is None
    assert not stale_report.exists()


async def test_patch_uses_checkpoint_git_metadata_not_agent_config_offline(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    source_repo = make_repo(tmp_path / "source")
    checkpoint_tree = tmp_path / "checkpoint"
    agent_tree = tmp_path / "agent"
    shutil.copytree(source_repo, checkpoint_tree, symlinks=True)
    shutil.copytree(source_repo, agent_tree, symlinks=True)
    marker = tmp_path / "hostile-diff-ran"
    hostile = agent_tree / "fake-diff.sh"
    hostile.write_text(f"#!/bin/sh\nprintf ran > {str(marker)!r}\nexit 99\n")
    hostile.chmod(0o755)
    subprocess.run(
        ["git", "config", "diff.external", "./fake-diff.sh"],
        cwd=agent_tree,
        check=True,
    )
    (agent_tree / "notes.txt").write_text("real patch content\n")
    snapshot_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkpoint_tree,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    checkpoint_archive = _tar_bytes(checkpoint_tree)
    agent_archive = _tar_bytes(agent_tree)
    checkpoint_id = "sha256:" + "0" * 64

    class FakePatchExecutor(docker_module.DockerExecutor):
        async def _checked_docker(self, *args, **kwargs):
            if args[0] == "cp":
                return agent_archive if args[1].startswith("agent-container:") else checkpoint_archive
            if args[0] in {"run", "create"}:
                return b"staging-container\n"
            raise AssertionError(f"unexpected docker command: {args}")

        async def _docker(self, *args, **kwargs):
            if args[0] == "rm":
                return b"", b"", 0, False, docker_module._now(), 0.1
            raise AssertionError(f"unexpected docker command: {args}")

    executor = FakePatchExecutor(tmp_path / "executor", MemorySink(), "offline-patch")
    branch = Branch(
        id="b1",
        run_id="offline-patch",
        head="sha256:" + "1" * 64,
        origin=checkpoint_id,
    )
    spec = docker_module._ContainerSpec("/workspace", "python", None)
    executor._containers[branch.id] = "agent-container"
    executor._specs[branch.id] = spec
    executor._checkpoint_specs[checkpoint_id] = spec

    receipt = await executor.patch(branch, snapshot_sha)

    assert receipt.exit_code == 0 and receipt.diff is not None
    assert {item.path for item in receipt.diff.files} == {"fake-diff.sh", "notes.txt"}
    assert "real patch content" in Path(receipt.diff.patch_path).read_text()
    assert not marker.exists()
    assert receipt.image_before == receipt.image_after == branch.head


async def test_apply_patch_copies_exact_bytes_and_advances_image_offline(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    patch_text = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"

    class FakeApplyExecutor(docker_module.DockerExecutor):
        def __init__(self):
            super().__init__(tmp_path / "executor", MemorySink(), "offline-apply")
            self.copied = b""
            self.command = ""

        async def _docker(self, *args, **kwargs):
            if args[0] == "cp":
                self.copied = Path(args[1]).read_bytes()
                return b"", b"", 0, False, docker_module._now(), 0.1
            raise AssertionError(f"unexpected docker command: {args}")

        async def _execute(self, branch, cmd, timeout_s, env_overrides=None):
            self.command = cmd
            return b"", b"", 0, False, docker_module._now(), 0.1

        async def _commit(self, container):
            return "sha256:" + "3" * 64

        async def _tree_digest(self, branch):
            return "d" * 64

    executor = FakeApplyExecutor()
    branch = Branch(
        id="w1",
        run_id="offline-apply",
        head="sha256:" + "2" * 64,
        origin="sha256:" + "1" * 64,
    )
    executor._containers[branch.id] = "offline-apply-w1"
    executor._specs[branch.id] = docker_module._ContainerSpec("/workspace", "python", None)

    receipt = await executor.apply_patch(branch, patch_text)

    assert executor.copied == patch_text.encode()
    assert executor.command.startswith("git update-index -q --refresh; git apply --index ")
    assert receipt.kind == "apply" and receipt.exit_code == 0
    assert receipt.patch_sha256 == hashlib.sha256(patch_text.encode()).hexdigest()
    assert receipt.image_after == branch.head == "sha256:" + "3" * 64
    assert receipt.tree_digest == "d" * 64


def test_tree_digest_from_archive_tracks_content_and_mode_but_ignores_git(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    workdir = tmp_path / "workdir"
    (workdir / ".git").mkdir(parents=True)
    (workdir / "src").mkdir()
    source = workdir / "src" / "app.py"
    source.write_text("VALUE = 1\n")
    (workdir / ".git" / "config").write_text("first\n")

    initial = docker_module._tree_digest_from_archive(_tar_bytes(workdir))
    (workdir / ".git" / "config").write_text("second\n")
    git_changed = docker_module._tree_digest_from_archive(_tar_bytes(workdir))
    source.write_text("VALUE = 2\n")
    content_changed = docker_module._tree_digest_from_archive(_tar_bytes(workdir))
    source.chmod(0o755)
    mode_changed = docker_module._tree_digest_from_archive(_tar_bytes(workdir))

    assert git_changed == initial
    assert content_changed != initial
    assert mode_changed != content_changed


async def test_start_container_overrides_entrypoint(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")

    class CaptureStartExecutor(docker_module.DockerExecutor):
        def __init__(self):
            super().__init__(tmp_path / "executor", MemorySink(), "entrypoint")
            self.args = ()

        async def _checked_docker(self, *args, **kwargs):
            self.args = args
            return b"container-id\n"

    executor = CaptureStartExecutor()
    spec = docker_module._ContainerSpec("/workspace", "python", None)

    await executor._start_container(TEST_IMAGE, "entrypoint-base", spec)

    entrypoint_index = executor.args.index("--entrypoint")
    assert executor.args[entrypoint_index + 1] == "tail"
    assert executor.args[-3:] == (TEST_IMAGE, "-f", "/dev/null")


async def test_start_failure_tracks_container_owned_by_executor(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")

    class FailedStartExecutor(docker_module.DockerExecutor):
        async def _checked_docker(self, *args, **kwargs):
            raise RuntimeError("docker run failed")

        async def _is_owned_container(self, name):
            return True

    executor = FailedStartExecutor(tmp_path / "executor", MemorySink(), "failed-start")
    spec = docker_module._ContainerSpec("/workspace", "python", None)

    with pytest.raises(RuntimeError, match="docker run failed"):
        await executor._start_container(TEST_IMAGE, "failed-start-base", spec)

    assert executor._created_containers == ["failed-start-base"]


async def test_image_declared_volume_is_rejected_before_start(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")

    class VolumeImageExecutor(docker_module.DockerExecutor):
        async def _checked_docker(self, *args, **kwargs):
            return b'{"/workspace":{}}\n'

    executor = VolumeImageExecutor(tmp_path / "executor", MemorySink(), "volume")

    with pytest.raises(ValueError, match="volume"):
        await executor._reject_image_volumes(TEST_IMAGE)


def test_anchored_write_rejects_retargeted_root(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")
    root = tmp_path / "workspace"
    root.mkdir()
    stat_result = root.stat()
    moved = tmp_path / "moved"
    root.rename(moved)
    root.symlink_to(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            docker_module._WRITE_FILE,
            str(root),
            str(stat_result.st_dev),
            str(stat_result.st_ino),
            "escaped.txt",
        ],
        input=b"escaped",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert b"outside" in completed.stderr
    assert not (tmp_path / "escaped.txt").exists()


async def test_execute_kills_surviving_processes_before_returning(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")

    class CleanupExecutor(docker_module.DockerExecutor):
        def __init__(self):
            super().__init__(tmp_path / "executor", MemorySink(), "cleanup")
            self.cleaned = False

        async def _docker(self, *args, **kwargs):
            return b"", b"", 0, False, None, 0.1

        async def _kill_surviving_processes(self, container):
            self.cleaned = True

    executor = CleanupExecutor()
    branch = Branch(id="base", run_id="cleanup", head="sha256:" + "0" * 64, origin="origin")
    executor._containers[branch.id] = "cleanup-base"
    executor._specs[branch.id] = docker_module._ContainerSpec("/workspace", "python", None)

    await executor._execute(branch, "true", 10)

    assert executor.cleaned is True


async def test_host_timeout_restarts_container_before_returning(tmp_path):
    docker_module = importlib.import_module("receipts.sandbox.docker")

    class RestartExecutor(docker_module.DockerExecutor):
        def __init__(self):
            super().__init__(tmp_path / "executor", MemorySink(), "restart")
            self.restarted = False

        async def _docker(self, *args, **kwargs):
            return b"", b"", None, True, None, 15.0

        async def _restart_container(self, container):
            self.restarted = True

    executor = RestartExecutor()
    branch = Branch(id="base", run_id="restart", head="sha256:" + "0" * 64, origin="origin")
    executor._containers[branch.id] = "restart-base"
    executor._specs[branch.id] = docker_module._ContainerSpec("/workspace", "python", None)

    result = await executor._execute(branch, "sleep 30", 10)

    assert result[3] is True
    assert executor.restarted is True
