import hashlib
import importlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from receipts.models import Branch, Receipt
from receipts.sandbox.protocol import CheckpointTampered, ImageSource
from receipts.sandbox.sink import MemorySink


def _daytona_module():
    try:
        return importlib.import_module("receipts.sandbox.daytona")
    except ModuleNotFoundError:
        pytest.fail("the Daytona executor module is not implemented")


class MemoryDaytonaApi:
    """In-memory Daytona fake. No method reaches the network or a local shell."""

    def __init__(self, module, max_sandboxes=None):
        self.module = module
        self.max_sandboxes = max_sandboxes
        self.max_active_sandboxes = 0
        self.sandboxes = {}
        self.snapshots = {}
        self.create_calls = []
        self.exec_calls = []
        self.upload_calls = []
        self.download_calls = []
        self.file_read_calls = []
        self.file_info_timeouts = []
        self.list_calls = []
        self.deleted_sandboxes = []
        self.deleted_snapshots = []
        self.timeout_commands = set()
        self.command_results = {}
        self.snapshot_delete_status = None
        self.closed = False
        self._sandbox_number = 0
        self._snapshot_number = 0

    def _new_sandbox(self, labels, files=None, modes=None, directories=None):
        if self.max_sandboxes is not None and len(self.sandboxes) >= self.max_sandboxes:
            raise RuntimeError(f"sandbox cap exceeded: {self.max_sandboxes}")
        self._sandbox_number += 1
        sandbox_id = f"sandbox-{self._sandbox_number}"
        self.sandboxes[sandbox_id] = {
            "labels": dict(labels),
            "files": deepcopy(files or {}),
            "modes": deepcopy(modes or {}),
            "directories": deepcopy(directories or {}),
        }
        self.max_active_sandboxes = max(self.max_active_sandboxes, len(self.sandboxes))
        return self.module.DaytonaSandbox(id=sandbox_id)

    def replace_tree(self, sandbox_id, source, remote_root="/repo"):
        files = {}
        modes = {}
        directories = {}
        for directory, names, filenames in os.walk(source, followlinks=False):
            directory_path = Path(directory)
            for name in names:
                path = directory_path / name
                remote_path = f"{remote_root}/{path.relative_to(source).as_posix()}"
                if path.is_symlink():
                    directories[remote_path] = 0o777
                else:
                    directories[remote_path] = stat.S_IMODE(path.stat().st_mode)
            for name in filenames:
                path = directory_path / name
                if path.is_symlink() and not path.exists():
                    continue
                remote_path = f"{remote_root}/{path.relative_to(source).as_posix()}"
                files[remote_path] = path.read_bytes()
                modes[remote_path] = stat.S_IMODE(path.stat().st_mode)
        self.sandboxes[sandbox_id]["files"] = files
        self.sandboxes[sandbox_id]["modes"] = modes
        self.sandboxes[sandbox_id]["directories"] = directories

    def set_file(self, sandbox_id, path, content, mode=0o644):
        self.sandboxes[sandbox_id]["files"][path] = content
        self.sandboxes[sandbox_id]["modes"][path] = mode
        parent = PurePosixPath(path).parent
        while parent != parent.parent:
            self.sandboxes[sandbox_id]["directories"].setdefault(str(parent), 0o755)
            parent = parent.parent

    async def create_from_image(
        self,
        image,
        *,
        resources,
        labels,
        auto_stop_minutes,
        ttl_minutes,
        timeout_s,
    ):
        self.create_calls.append(
            {
                "kind": "image",
                "image": image,
                "resources": resources,
                "labels": dict(labels),
                "auto_stop_minutes": auto_stop_minutes,
                "ttl_minutes": ttl_minutes,
                "timeout_s": timeout_s,
            },
        )
        return self._new_sandbox(
            labels,
            {"/repo/original.txt": b"original\n"},
            {"/repo/original.txt": 0o644},
        )

    async def create_from_snapshot(
        self,
        snapshot,
        *,
        labels,
        auto_stop_minutes,
        ttl_minutes,
        timeout_s,
    ):
        self.create_calls.append(
            {
                "kind": "snapshot",
                "snapshot": snapshot,
                "labels": dict(labels),
                "auto_stop_minutes": auto_stop_minutes,
                "ttl_minutes": ttl_minutes,
                "timeout_s": timeout_s,
            },
        )
        return self._new_sandbox(
            labels,
            self.snapshots[snapshot]["files"],
            self.snapshots[snapshot]["modes"],
            self.snapshots[snapshot]["directories"],
        )

    async def exec(self, sandbox_id, command, *, cwd, timeout_s, env=None):
        self.exec_calls.append(
            {
                "sandbox_id": sandbox_id,
                "command": command,
                "cwd": cwd,
                "timeout_s": timeout_s,
                "env": env,
            },
        )
        if command in self.timeout_commands:
            raise self.module.DaytonaCommandTimeout(command)
        if command in self.command_results:
            return self.command_results[command]
        if "/opt/receipts/receipts_pytest.py" in command:
            report_arg = next(
                token
                for token in shlex.split(command)
                if token.startswith("--junitxml=")
            )
            report_path = report_arg.split("=", 1)[1]
            self.set_file(
                sandbox_id,
                report_path,
                (
                    b'<?xml version="1.0"?><testsuites><testsuite>'
                    b'<testcase classname="tests.test_sample" name="test_ok" '
                    b'file="tests/test_sample.py" />'
                    b"</testsuite></testsuites>"
                ),
            )
            return self.module.DaytonaCommandResult(
                exit_code=0,
                output="tests/test_sample.py::test_ok PASSED\n",
            )
        if "git rev-parse HEAD" in command:
            snapshot_sha = getattr(self, "snapshot_sha", "a" * 40)
            return self.module.DaytonaCommandResult(exit_code=0, output=snapshot_sha + "\n")
        return self.module.DaytonaCommandResult(exit_code=0, output=f"ran:{command}")

    async def upload_file(self, sandbox_id, content, remote_path, *, timeout_s):
        self.upload_calls.append((sandbox_id, content, remote_path, timeout_s))
        self.sandboxes[sandbox_id]["files"][remote_path] = bytes(content)
        self.sandboxes[sandbox_id]["modes"][remote_path] = 0o644

    async def download_file(self, sandbox_id, remote_path, *, timeout_s):
        self.file_read_calls.append(("download", remote_path))
        state = self.sandboxes[sandbox_id]
        if remote_path in state["directories"]:
            raise RuntimeError("the live service refuses to download a directory")
        return state["files"].get(remote_path)

    async def get_file_info(self, sandbox_id, remote_path, *, timeout_s):
        self.file_read_calls.append(("info", remote_path))
        self.file_info_timeouts.append(timeout_s)
        state = self.sandboxes[sandbox_id]
        if remote_path in state["directories"]:
            mode = state["directories"][remote_path]
            return self.module.DaytonaFile(
                path=remote_path,
                is_dir=True,
                mode="drwxr-xr-x",
                permissions=f"{mode:04o}",
                size=0,
            )
        if remote_path in state["files"]:
            mode = state["modes"].get(remote_path, 0o644)
            return self.module.DaytonaFile(
                path=remote_path,
                is_dir=False,
                mode="-rwxr-xr-x" if mode & 0o111 else "-rw-r--r--",
                permissions=f"{mode:04o}",
                size=len(state["files"][remote_path]),
            )
        return None

    async def download_files(self, sandbox_id, requests, *, timeout_s):
        self.download_calls.extend(request.source for request in requests)
        responses = []
        for request in requests:
            content = self.sandboxes[sandbox_id]["files"].get(request.source)
            if content is None:
                responses.append(
                    self.module.DaytonaDownloadResult(
                        source=request.source,
                        result=None,
                        error="missing",
                    ),
                )
            else:
                if request.destination is not None:
                    destination = Path(request.destination)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                    result = request.destination
                else:
                    result = content
                responses.append(
                    self.module.DaytonaDownloadResult(
                        source=request.source,
                        result=result,
                        error=None,
                    ),
                )
        return responses

    async def list_files(self, sandbox_id, path, *, depth):
        self.list_calls.append((sandbox_id, path, depth))
        prefix = path.rstrip("/") + "/"

        def included(candidate):
            if not candidate.startswith(prefix):
                return False
            relative = PurePosixPath(candidate.removeprefix(prefix))
            return bool(relative.parts) and len(relative.parts) <= depth

        directories = [
            self.module.DaytonaFile(
                path=directory_path,
                is_dir=True,
                mode="drwxr-xr-x",
                permissions=f"{mode:04o}",
                size=0,
            )
            for directory_path, mode in sorted(
                self.sandboxes[sandbox_id]["directories"].items(),
            )
            if included(directory_path)
        ]
        files = [
            self.module.DaytonaFile(
                path=file_path,
                is_dir=False,
                mode=(
                    "-rwxr-xr-x"
                    if self.sandboxes[sandbox_id]["modes"].get(file_path, 0o644) & 0o111
                    else "-rw-r--r--"
                ),
                permissions=f"{self.sandboxes[sandbox_id]['modes'].get(file_path, 0o644):04o}",
                size=len(content),
            )
            for file_path, content in self.sandboxes[sandbox_id]["files"].items()
            if included(file_path)
        ]
        return directories + files

    async def create_snapshot(self, sandbox_id, name, *, timeout_s):
        self._snapshot_number += 1
        snapshot = self.module.DaytonaSnapshot(
            id=f"snapshot-{self._snapshot_number}",
            name=name,
            ref=f"registry.example/{name}:daytona",
        )
        self.snapshots[name] = {
            "snapshot": snapshot,
            "files": deepcopy(self.sandboxes[sandbox_id]["files"]),
            "modes": deepcopy(self.sandboxes[sandbox_id]["modes"]),
            "directories": deepcopy(self.sandboxes[sandbox_id]["directories"]),
        }
        return snapshot

    async def get_snapshot(self, name):
        return self.snapshots[name]["snapshot"]

    async def list_sandboxes(self, labels):
        return [
            self.module.DaytonaSandbox(id=sandbox_id)
            for sandbox_id, state in self.sandboxes.items()
            if all(state["labels"].get(key) == value for key, value in labels.items())
        ]

    async def delete_sandbox(self, sandbox_id, *, timeout_s):
        self.deleted_sandboxes.append(sandbox_id)
        self.sandboxes.pop(sandbox_id, None)

    async def delete_snapshot(self, snapshot, *, timeout_s):
        self.deleted_snapshots.append(snapshot)
        if self.snapshot_delete_status is not None:
            error = RuntimeError("snapshot delete denied")
            error.status_code = self.snapshot_delete_status
            raise error
        for name, state in list(self.snapshots.items()):
            if snapshot in (name, state["snapshot"].id):
                self.snapshots.pop(name)

    async def close(self):
        self.closed = True


def _executor(tmp_path, module, api=None, **kwargs):
    fake = api or MemoryDaytonaApi(module)
    sink = MemorySink()
    executor = module.DaytonaExecutor(
        tmp_path / "executor",
        sink,
        "run-1",
        fake,
        **kwargs,
    )
    return executor, fake, sink


class ManualClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


def _symlink_repository(path):
    (path / "real-dir").mkdir(parents=True)
    (path / "target.txt").write_text("target before\n")
    (path / "unrelated.txt").write_text("unrelated before\n")
    (path / "real-dir" / "nested.txt").write_text("nested\n")
    (path / "file-link").symlink_to("target.txt")
    (path / "directory-link").symlink_to("real-dir", target_is_directory=True)
    (path / "dangling-link").symlink_to("missing.txt")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.com"],
        cwd=path,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize(
    "workdir",
    [
        "/",
        "/tmp",
        "/tmp/scratch",
        "/tmp/scratch/repo",
        "/tmp/repo",
        "//tmp",
        "//tmp/scratch",
        "//tmp/scratch/repo",
    ],
)
def test_workdir_must_not_overlap_scratch(workdir):
    module = _daytona_module()

    with pytest.raises(ValueError):
        module.DaytonaExecutor._validate_workdir(workdir)


async def test_prepare_uses_default_resources_labels_bootstrap_and_setup(tmp_path):
    module = _daytona_module()
    executor, api, sink = _executor(tmp_path, module)
    source = ImageSource(
        image="swerebench/example:1",
        workdir="/repo",
        python="python3",
        setup=["apply human test patch"],
    )

    base = await executor.prepare(source)

    assert api.create_calls == [
        {
            "kind": "image",
            "image": "swerebench/example:1",
            "resources": module.DaytonaResources(cpu=2, memory=2, disk=5),
            "labels": {"receipts_run": "run-1", "receipts_branch": "base"},
            "auto_stop_minutes": 60,
            "ttl_minutes": None,
            "timeout_s": 900,
        },
    ]
    assert api.exec_calls[0]["command"] == "mkdir -p /opt/receipts/reports"
    assert api.exec_calls[0]["timeout_s"] > 0
    bootstrap_upload = api.upload_calls[0]
    assert bootstrap_upload[2] == "/opt/receipts/receipts_pytest.py"
    assert b"import pytest" in bootstrap_upload[1]
    assert base == Branch(
        id="base",
        run_id="run-1",
        head="sandbox-1#1",
        origin="sandbox-1",
    )
    assert [(receipt.cmd, receipt.seq) for receipt in sink.receipts] == [
        ("apply human test patch", 1),
    ]


async def test_resources_and_auto_stop_are_configurable(tmp_path):
    module = _daytona_module()
    resources = module.DaytonaResources(cpu=4, memory=8, disk=10)
    executor, api, _ = _executor(
        tmp_path,
        module,
        resources=resources,
        auto_stop_minutes=30,
        ttl_minutes=240,
    )

    await executor.prepare(ImageSource(image="example:1", workdir="/repo"))

    call = api.create_calls[0]
    assert call["resources"] == resources
    assert call["auto_stop_minutes"] == 30
    assert call["ttl_minutes"] == 240


async def test_sandbox_usage_reports_lifetimes_and_resources_from_injected_clock(
    tmp_path,
):
    module = _daytona_module()
    clock = ManualClock(10.0)
    created_at = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    wall_clock = ManualClock(created_at)
    resources = module.DaytonaResources(cpu=4, memory=8, disk=10)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cost_path = run_dir / "cost.json"
    cost_path.write_text('{"estimated_dollars": 1.25}\n', encoding="utf-8")
    executor, _, _ = _executor(
        tmp_path,
        module,
        resources=resources,
        clock=clock,
        wall_clock=wall_clock,
        cleanup_manifest=run_dir / "cleanup.json",
    )

    await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    clock.value = 25.5
    wall_clock.value = created_at + timedelta(seconds=16)
    await executor.close()

    usage = executor.sandbox_usage()
    assert usage == [
        {
            "sandbox_id": "sandbox-1",
            "seconds": 15.5,
            "created_at": "2026-10-02T12:00:00+00:00",
            "deleted_at": "2026-10-02T12:00:16+00:00",
            "resources": {"cpu": 4, "memory": 8, "disk": 10},
        },
    ]
    assert usage[0]["created_at"] <= usage[0]["deleted_at"]
    persisted_cost = json.loads(cost_path.read_text(encoding="utf-8"))
    assert persisted_cost["estimated_dollars"] == 1.25
    assert persisted_cost["sandbox_usage"] == usage


async def test_run_write_read_and_snapshot_form_one_complete_provenance_chain(tmp_path):
    module = _daytona_module()
    executor, api, sink = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    api.command_results["mixed output"] = module.DaytonaCommandResult(
        exit_code=3,
        output="hello\nerror\n",
    )

    command = await executor.run(base, "mixed output", timeout_s=17)
    written = await executor.write_file(base, "pkg/new.py", "VALUE = 1\n")
    snapshot = await executor.snapshot(base)

    assert command.seq == 1 and command.receipt_id == "base-1"
    assert command.image_before == "sandbox-1"
    assert command.image_after == "sandbox-1#1"
    assert command.exit_code == 3 and command.timed_out is False
    assert command.stdout_tail == "hello\nerror\n" and command.stderr_tail == ""
    assert command.stdout_sha256 == hashlib.sha256(b"hello\nerror\n").hexdigest()
    assert Path(command.log_path).read_bytes() == b"hello\nerror\n"
    assert written.seq == 2
    assert written.image_before == "sandbox-1#1"
    assert written.image_after == "sandbox-1#2"
    assert await executor.read_file(base, "pkg/new.py", 7) == "VALUE ="
    assert snapshot.seq == 3 and snapshot.snapshot_sha == "a" * 40
    assert snapshot.image_before == "sandbox-1#2"
    assert snapshot.image_after == base.head == "sandbox-1#3"
    assert sink.receipts[-1].snapshot_sha == "a" * 40
    assert [receipt.seq for receipt in sink.receipts] == [1, 2, 3]


async def test_read_file_lists_directory_entries_sorted_with_slashes(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    api.set_file("sandbox-1", "/repo/listing/z.py", b"z\n")
    api.set_file("sandbox-1", "/repo/listing/sub/nested.py", b"nested\n")
    api.set_file("sandbox-1", "/repo/listing/a.py", b"a\n")

    assert await executor.read_file(base, "listing", 100) == (
        "a.py\nsub/\nz.py\n"
    )
    assert api.file_read_calls == [("info", "/repo/listing")]


async def test_read_file_treats_missing_file_info_as_missing(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))

    assert await executor.read_file(base, "missing", 100) == ""
    assert api.file_read_calls == [("info", "/repo/missing")]


async def test_read_file_checks_info_before_downloading_regular_file(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))

    assert await executor.read_file(base, "original.txt", 100) == "original\n"
    assert api.file_read_calls == [
        ("info", "/repo/original.txt"),
        ("download", "/repo/original.txt"),
    ]
    assert api.file_info_timeouts == [executor.file_timeout_s]


async def test_read_file_propagates_non_not_found_file_info_error(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))

    async def failed_info(sandbox_id, remote_path, *, timeout_s=None):
        raise RuntimeError("file info denied")

    api.get_file_info = failed_info

    with pytest.raises(RuntimeError, match="file info denied"):
        await executor.read_file(base, "original.txt", 100)


async def test_timeout_becomes_a_receipt_and_passes_the_explicit_timeout(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    api.timeout_commands.add("sleep forever")

    receipt = await executor.run(base, "sleep forever", timeout_s=5)

    assert receipt.timed_out is True and receipt.exit_code is None
    assert receipt.stdout_tail == "" and receipt.stderr_tail == ""
    assert receipt.stdout_sha256 == hashlib.sha256(b"").hexdigest()
    assert api.exec_calls[-1]["timeout_s"] == 5
    assert receipt.image_before == "sandbox-1"
    assert receipt.image_after == "sandbox-1#1"


async def test_run_pytest_uses_trusted_runner_and_reads_junit_through_fs(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(
        ImageSource(image="example:1", workdir="/repo", python="python3"),
    )

    receipt = await executor.run_pytest(
        base,
        "tests/test_sample.py::test_ok",
        timeout_s=37,
        kind="verification",
    )

    call = api.exec_calls[-1]
    assert call["command"] == (
        "python3 -I /opt/receipts/receipts_pytest.py "
        "tests/test_sample.py::test_ok "
        "-o junit_family=xunit1 -p no:cacheprovider -rA --continue-on-collection-errors "
        "--junitxml=/opt/receipts/reports/base-1.xml"
    )
    assert call["timeout_s"] == 37
    assert call["env"] == {"PYTEST_ADDOPTS": "", "PYTEST_PLUGINS": ""}
    assert receipt.kind == "verification" and receipt.exit_code == 0
    assert receipt.junit is not None
    assert receipt.junit.passed == ["tests/test_sample.py::test_ok"]
    assert receipt.tree_digest is not None
    assert receipt.tree_download_s is not None
    assert receipt.tree_download_s >= 0
    old_receipt = Receipt.model_validate(
        receipt.model_dump(exclude={"tree_download_s"}),
    )
    assert old_receipt.tree_download_s is None
    assert receipt.image_before == "sandbox-1"
    assert receipt.image_after == base.head == "sandbox-1#1"
    assert Path(receipt.log_path).read_text() == "tests/test_sample.py::test_ok PASSED\n"


@pytest.mark.parametrize("path", ["", ".", "../escape.py", "a/../escape.py", "/escape.py"])
async def test_write_refuses_paths_outside_the_repository(tmp_path, path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))

    receipt = await executor.write_file(base, path, "escape")

    assert receipt.exit_code == 1
    assert receipt.path == path
    assert "outside" in receipt.stderr_tail
    assert "/escape.py" not in api.sandboxes["sandbox-1"]["files"]


async def test_read_refuses_invalid_paths_and_validates_the_byte_limit(tmp_path):
    module = _daytona_module()
    executor, _, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))

    assert await executor.read_file(base, "../original.txt", 100) == ""
    assert await executor.read_file(base, "/repo/original.txt", 100) == ""
    assert await executor.read_file(base, "missing.txt", 100) == ""
    assert await executor.read_file(base, "original.txt", 4) == "orig"
    with pytest.raises(ValueError, match="non-negative"):
        await executor.read_file(base, "original.txt", -1)


async def test_checkpoint_and_fork_use_snapshot_ref_labels_and_isolated_files(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    written = await executor.write_file(base, "checkpoint.txt", "frozen\n")

    checkpoint = await executor.checkpoint(base)
    first, second = await executor.fork(checkpoint, 2)

    snapshot = next(iter(api.snapshots.values()))["snapshot"]
    assert checkpoint.id == checkpoint.digest == snapshot.ref
    assert checkpoint.parent == written.image_after
    fork_calls = [call for call in api.create_calls if call["kind"] == "snapshot"]
    assert [call["snapshot"] for call in fork_calls] == [snapshot.name, snapshot.name]
    assert [call["labels"] for call in fork_calls] == [
        {"receipts_run": "run-1", "receipts_branch": "b1"},
        {"receipts_run": "run-1", "receipts_branch": "b2"},
    ]
    assert first.head == first.origin == checkpoint.id
    assert second.head == second.origin == checkpoint.id
    await executor.write_file(first, "only-first.txt", "first\n")
    assert await executor.read_file(first, "only-first.txt", 100) == "first\n"
    assert await executor.read_file(second, "only-first.txt", 100) == ""
    (witness,) = await executor.fork(checkpoint, 1, prefix="w")
    assert witness.id == "w1"


async def test_scratch_is_outside_repository_evidence_and_checkpoint(tmp_path):
    module = _daytona_module()
    repository = tmp_path / "repository"
    snapshot_sha = _symlink_repository(repository)
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    api.replace_tree("sandbox-1", repository)
    api.snapshot_sha = snapshot_sha
    snapshot = await executor.snapshot(base)
    checkpoint = await executor.checkpoint(base)
    (agent,) = await executor.fork(checkpoint, 1, prefix="agent")
    scratch = executor.scratch_path(agent)
    assert await executor.read_file(agent, f"{scratch}/probe.py", 100) == ""

    before_digest = await executor._tree_digest(agent)
    first = await executor.write_file(
        agent,
        "/tmp/debug_build.py",
        "print('debug')\n",
    )
    second = await executor.write_file(
        agent,
        "/tmp/x/y.py",
        "print('nested')\n",
    )
    refused = [
        await executor.write_file(agent, path, "refused\n")
        for path in ("/tmp/../etc/passwd", "/tmpx/a.py", "/tmp")
    ]
    after_digest = await executor._tree_digest(agent)
    patch = await executor.patch(agent, snapshot.snapshot_sha)
    (witness,) = await executor.fork(checkpoint, 1, prefix="w")

    assert scratch == "/tmp"
    assert first.exit_code == second.exit_code == 0
    assert await executor.read_file(agent, "/tmp/debug_build.py", 100) == (
        "print('debug')\n"
    )
    assert await executor.read_file(agent, "/tmp/x/y.py", 100) == (
        "print('nested')\n"
    )
    assert all(item.exit_code == 1 for item in refused)
    assert all("outside" in item.stderr_tail for item in refused)
    refused_reads = [
        await executor.read_file(agent, path, 100)
        for path in ("/tmp/../etc/passwd", "/tmpx/a.py", "/tmp")
    ]
    assert refused_reads == ["", "", ""]
    assert after_digest == before_digest
    assert patch.tree_digest == before_digest
    assert patch.diff is not None and patch.diff.files == []
    assert Path(patch.diff.patch_path).read_text() == ""
    assert await executor.read_file(witness, "/tmp/debug_build.py", 100) == ""
    assert await executor.read_file(witness, "/tmp/x/y.py", 100) == ""


async def test_checkpoint_persists_cleanup_manifest_and_close_marks_snapshot_deleted(
    tmp_path,
):
    module = _daytona_module()
    cleanup_manifest = tmp_path / "run" / "cleanup.json"
    executor, api, _ = _executor(
        tmp_path,
        module,
        cleanup_manifest=cleanup_manifest,
    )
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))

    await executor.checkpoint(base)

    snapshot = next(iter(api.snapshots.values()))["snapshot"]
    created = json.loads(cleanup_manifest.read_text(encoding="utf-8"))
    assert created == [
        {
            "id": snapshot.id,
            "name": snapshot.name,
            "created_at": created[0]["created_at"],
            "status": "created",
            "error": None,
        },
    ]
    datetime.fromisoformat(created[0]["created_at"])

    await executor.close()

    deleted = json.loads(cleanup_manifest.read_text(encoding="utf-8"))
    assert deleted[0]["status"] == "deleted"
    assert deleted[0]["error"] is None


async def test_fork_rejects_a_changed_snapshot_ref(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    checkpoint = await executor.checkpoint(base)
    name = next(iter(api.snapshots))
    original = api.snapshots[name]["snapshot"]
    api.snapshots[name]["snapshot"] = module.DaytonaSnapshot(
        id=original.id,
        name=original.name,
        ref="registry.example/changed:daytona",
    )

    with pytest.raises(CheckpointTampered, match="modified after prepare"):
        await executor.fork(checkpoint, 1)


async def test_checkpoint_restores_downloaded_symlinks_from_the_trusted_index(tmp_path):
    module = _daytona_module()
    repository = tmp_path / "repository"
    snapshot_sha = _symlink_repository(repository)
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    api.replace_tree("sandbox-1", repository)
    api.snapshot_sha = snapshot_sha
    await executor.snapshot(base)
    sandbox_commands = list(api.exec_calls)
    api.download_calls.clear()

    checkpoint = await executor.checkpoint(base)

    assert api.exec_calls == sandbox_commands
    assert any(path.startswith("/repo/.git/") for path in api.download_calls)
    checkpoint_tree = executor._checkpoint_trees[checkpoint.id]
    assert (checkpoint_tree / "file-link").is_symlink()
    assert os.readlink(checkpoint_tree / "file-link") == "target.txt"
    assert (checkpoint_tree / "directory-link").is_symlink()
    assert os.readlink(checkpoint_tree / "directory-link") == "real-dir"
    assert (checkpoint_tree / "dangling-link").is_symlink()
    assert os.readlink(checkpoint_tree / "dangling-link") == "missing.txt"


async def test_patch_downloads_tree_preserves_exec_bits_and_static_copies_symlinks(
    tmp_path,
):
    module = _daytona_module()
    repository = tmp_path / "repository"
    (repository / "src").mkdir(parents=True)
    (repository / "src" / "app.py").write_text("VALUE = 1\n")
    (repository / "link.py").symlink_to("src/app.py")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repository, check=True)
    snapshot_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    reference = tmp_path / "reference"
    shutil.copytree(repository, reference, symlinks=True)
    (reference / "src" / "app.py").write_text("VALUE = 2\n")
    reference_tool = reference / "bin" / "tool"
    reference_tool.parent.mkdir()
    reference_tool.write_text("#!/bin/sh\nexit 0\n")
    reference_tool.chmod(0o755)
    subprocess.run(["git", "add", "-A"], cwd=reference, check=True)
    expected_patch = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            snapshot_sha,
        ],
        cwd=reference,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    api.replace_tree("sandbox-1", repository)
    api.snapshot_sha = snapshot_sha
    snapshot = await executor.snapshot(base)
    sandbox_commands = list(api.exec_calls)
    checkpoint = await executor.checkpoint(base)
    (agent,) = await executor.fork(checkpoint, 1, prefix="agent")
    agent_id = api.create_calls[-1]["labels"]["receipts_branch"]
    assert agent_id == agent.id
    sandbox_id = executor._sandboxes[agent.id]
    api.set_file(sandbox_id, "/repo/src/app.py", b"VALUE = 2\n")
    api.set_file(sandbox_id, "/repo/link.py", b"VALUE = 2\n")
    api.set_file(sandbox_id, "/repo/bin/tool", b"#!/bin/sh\nexit 0\n", 0o755)
    api.set_file(sandbox_id, "/repo/pkg/vendor/.git", b"nested metadata\n")
    marker = tmp_path / "hostile-diff-ran"
    api.set_file(
        sandbox_id,
        "/repo/.git/config",
        (
            repository.joinpath(".git/config").read_bytes()
            + f"\n[diff]\n\texternal = printf ran > {marker}\n".encode()
        ),
    )
    api.download_calls.clear()

    receipt = await executor.patch(agent, snapshot.snapshot_sha)

    assert receipt.exit_code == 0 and receipt.diff is not None
    patch_text = Path(receipt.diff.patch_path).read_text()
    assert patch_text == expected_patch
    assert "diff --git a/src/app.py b/src/app.py" in patch_text
    assert "diff --git a/bin/tool b/bin/tool" in patch_text
    assert "new file mode 100755" in patch_text
    assert "diff --git a/link.py b/link.py" not in patch_text
    assert "link.py" not in receipt.dropped_paths
    assert receipt.tree_digest is not None
    assert not any(path.startswith("/repo/.git/") for path in api.download_calls)
    assert "/repo/pkg/vendor/.git" in api.download_calls
    assert not marker.exists()
    assert api.exec_calls == sandbox_commands
    assert receipt.image_before == checkpoint.id
    assert receipt.image_after == agent.head == f"{checkpoint.id}#1"


async def test_patch_keeps_checkpoint_symlinks_and_applies_to_fresh_repositories(tmp_path):
    module = _daytona_module()
    repository = tmp_path / "repository"
    snapshot_sha = _symlink_repository(repository)
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    api.replace_tree("sandbox-1", repository)
    api.snapshot_sha = snapshot_sha
    snapshot = await executor.snapshot(base)
    sandbox_commands = list(api.exec_calls)
    checkpoint = await executor.checkpoint(base)
    unrelated_agent, target_agent = await executor.fork(
        checkpoint,
        2,
        prefix="agent",
    )

    unrelated_sandbox = executor._sandboxes[unrelated_agent.id]
    api.set_file(unrelated_sandbox, "/repo/unrelated.txt", b"unrelated after\n")
    unrelated_receipt = await executor.patch(unrelated_agent, snapshot.snapshot_sha)

    assert unrelated_receipt.exit_code == 0 and unrelated_receipt.diff is not None
    unrelated_patch = Path(unrelated_receipt.diff.patch_path).read_text()
    assert unrelated_patch.count("diff --git ") == 1
    assert "diff --git a/unrelated.txt b/unrelated.txt" in unrelated_patch
    assert "file-link" not in unrelated_patch
    assert "directory-link" not in unrelated_patch
    assert "dangling-link" not in unrelated_patch

    target_sandbox = executor._sandboxes[target_agent.id]
    api.set_file(target_sandbox, "/repo/target.txt", b"target after\n")
    api.set_file(target_sandbox, "/repo/file-link", b"target after\n")
    target_receipt = await executor.patch(target_agent, snapshot.snapshot_sha)

    assert target_receipt.exit_code == 0 and target_receipt.diff is not None
    target_patch = Path(target_receipt.diff.patch_path).read_text()
    assert target_patch.count("diff --git ") == 1
    assert "diff --git a/target.txt b/target.txt" in target_patch
    assert "file-link" not in target_patch
    assert "directory-link" not in target_patch
    assert "dangling-link" not in target_patch
    assert api.exec_calls == sandbox_commands

    for name, receipt in (
        ("fresh-unrelated", unrelated_receipt),
        ("fresh-target", target_receipt),
    ):
        fresh = tmp_path / name
        subprocess.run(
            ["git", "clone", "-q", "--no-hardlinks", str(repository), str(fresh)],
            check=True,
        )
        subprocess.run(
            ["git", "apply", "--index", receipt.diff.patch_path],
            cwd=fresh,
            check=True,
        )
        assert (fresh / "file-link").is_symlink()
        assert (fresh / "directory-link").is_symlink()
        assert (fresh / "dangling-link").is_symlink()

    assert (tmp_path / "fresh-unrelated" / "unrelated.txt").read_text() == (
        "unrelated after\n"
    )
    assert (tmp_path / "fresh-target" / "target.txt").read_text() == "target after\n"


async def test_apply_patch_uploads_exact_bytes_and_runs_in_the_witness(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    checkpoint = await executor.checkpoint(base)
    (witness,) = await executor.fork(checkpoint, 1, prefix="w")
    patch_text = (
        "diff --git a/original.txt b/original.txt\n"
        "--- a/original.txt\n"
        "+++ b/original.txt\n"
        "@@ -1 +1 @@\n"
        "-original\n"
        "+changed\n"
    )

    receipt = await executor.apply_patch(witness, patch_text)

    uploaded = api.upload_calls[-1]
    assert uploaded[1] == patch_text.encode()
    assert uploaded[2] == "/opt/receipts/w1-1-apply.diff"
    call = api.exec_calls[-1]
    assert call["command"] == (
        "git update-index -q --refresh; "
        "git apply -v --3way --recount --ignore-space-change --whitespace=nowarn /opt/receipts/w1-1-apply.diff"
    )
    assert call["cwd"] == "/repo"
    assert receipt.kind == "apply" and receipt.exit_code == 0
    assert receipt.patch_sha256 == hashlib.sha256(patch_text.encode()).hexdigest()
    assert receipt.tree_digest is not None
    assert receipt.image_before == checkpoint.id
    assert receipt.image_after == witness.head == f"{checkpoint.id}#1"


async def test_release_deletes_sandbox_once_preserves_snapshot_and_refuses_run(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    checkpoint = await executor.checkpoint(base)
    (agent,) = await executor.fork(checkpoint, 1, prefix="agent")
    sandbox_id = executor._sandboxes[agent.id]

    await executor.release(agent)
    await executor.release(agent)

    assert api.deleted_sandboxes.count(sandbox_id) == 1
    assert agent.id not in executor._sandboxes
    assert checkpoint.id in executor._snapshots
    with pytest.raises(RuntimeError, match="released Daytona branch: agent1"):
        await executor.run(agent, "true", timeout_s=5)


async def test_release_stays_within_three_sandbox_cap_across_two_witnesses(tmp_path):
    module = _daytona_module()
    api = MemoryDaytonaApi(module, max_sandboxes=3)
    executor, _, _ = _executor(tmp_path, module, api=api)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    checkpoint = await executor.checkpoint(base)

    await executor.release(base)
    (agent,) = await executor.fork(checkpoint, 1, prefix="agent")
    (first_witness,) = await executor.fork(checkpoint, 1, prefix="w")
    await executor.release(first_witness)
    (second_witness,) = await executor.fork(checkpoint, 1, prefix="w")
    await executor.release(second_witness)
    await executor.release(agent)

    assert [first_witness.id, second_witness.id] == ["w1", "w2"]
    assert api.max_active_sandboxes <= 3
    assert api.sandboxes == {}


async def test_close_records_snapshot_403_retains_it_and_retries_after_sandbox_cleanup(
    tmp_path,
):
    module = _daytona_module()
    cleanup_manifest = tmp_path / "run" / "cleanup.json"
    executor, api, _ = _executor(
        tmp_path,
        module,
        cleanup_manifest=cleanup_manifest,
    )
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    checkpoint = await executor.checkpoint(base)
    await executor.fork(checkpoint, 1)
    orphan = api._new_sandbox(
        {"receipts_run": "run-1", "receipts_branch": "leaked"},
    )
    foreign = api._new_sandbox(
        {"receipts_run": "another-run", "receipts_branch": "base"},
    )
    api.snapshot_delete_status = 403

    with pytest.raises(RuntimeError, match="snapshot delete denied"):
        await executor.close()

    assert set(api.deleted_sandboxes) == {"sandbox-1", "sandbox-2", orphan.id}
    assert foreign.id in api.sandboxes
    assert len(api.deleted_snapshots) == 1
    assert checkpoint.id in executor._snapshots
    failed = json.loads(cleanup_manifest.read_text(encoding="utf-8"))
    assert failed[0]["status"] == "delete_failed"
    assert failed[0]["error"] == "snapshot delete denied"
    assert api.closed is False

    api.snapshot_delete_status = None
    await executor.close()

    assert len(api.deleted_snapshots) == 2
    deleted = json.loads(cleanup_manifest.read_text(encoding="utf-8"))
    assert deleted[0]["status"] == "deleted"
    assert deleted[0]["error"] is None
    assert api.closed is True


class LaggingDeleteDaytonaApi(MemoryDaytonaApi):
    """Models the live service: a deleted sandbox stays listed while it is torn
    down, and deleting an id that is already gone raises a 404."""

    def __init__(self, module):
        super().__init__(module)
        self.destroying: set[str] = set()

    async def list_sandboxes(self, labels):
        listed = await super().list_sandboxes(labels)
        return listed + [
            self.module.DaytonaSandbox(id=sandbox_id)
            for sandbox_id in sorted(self.destroying)
        ]

    async def delete_sandbox(self, sandbox_id, *, timeout_s):
        self.deleted_sandboxes.append(sandbox_id)
        if sandbox_id not in self.sandboxes:
            error = RuntimeError(f"Sandbox with ID or name {sandbox_id} not found")
            error.status_code = 404
            raise error
        self.sandboxes.pop(sandbox_id)
        self.destroying.add(sandbox_id)


async def test_close_tolerates_sandboxes_still_listed_while_being_deleted(tmp_path):
    module = _daytona_module()
    api = LaggingDeleteDaytonaApi(module)
    executor, _, _ = _executor(tmp_path, module, api=api)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    checkpoint = await executor.checkpoint(base)
    await executor.fork(checkpoint, 2)
    orphan = api._new_sandbox({"receipts_run": "run-1", "receipts_branch": "leaked"})

    await executor.close()

    assert api.sandboxes == {}
    assert sorted(set(api.deleted_sandboxes)) == sorted(
        {"sandbox-1", "sandbox-2", "sandbox-3", orphan.id},
    )
    assert api.closed is True


async def test_close_counts_a_404_on_a_tracked_sandbox_as_deleted(tmp_path):
    module = _daytona_module()
    api = LaggingDeleteDaytonaApi(module)
    executor, _, _ = _executor(tmp_path, module, api=api)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    api.sandboxes.pop("sandbox-1")

    await executor.close()

    assert api.closed is True


async def test_close_retains_a_nonpermission_snapshot_failure_for_retry(tmp_path):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    await executor.checkpoint(base)
    api.snapshot_delete_status = 500

    with pytest.raises(RuntimeError, match="snapshot"):
        await executor.close()

    assert api.closed is False
    assert len(api.deleted_snapshots) == 1
    api.snapshot_delete_status = None

    await executor.close()

    assert len(api.deleted_snapshots) == 2
    assert api.closed is True


async def test_async_daytona_adapter_uses_the_installed_sdk_signatures(tmp_path):
    module = _daytona_module()
    from daytona import DaytonaFileNotFoundError, DaytonaProcessExecutionTimeoutError

    class SdkProcess:
        def __init__(self):
            self.calls = []
            self.timeout = False

        async def exec(self, command, cwd=None, env=None, timeout=None):
            self.calls.append((command, cwd, env, timeout))
            if self.timeout:
                raise DaytonaProcessExecutionTimeoutError("command execution timeout")
            return SimpleNamespace(exit_code=7, result="merged output")

    class SdkFs:
        def __init__(self):
            self.uploads = []
            self.downloads = []
            self.info_calls = []

        async def upload_file(self, content, remote_path, timeout=1800):
            self.uploads.append((content, remote_path, timeout))

        async def download_file(self, remote_path, timeout=1800):
            self.downloads.append((remote_path, timeout))
            if remote_path == "/repo":
                raise RuntimeError("the live service refuses to download a directory")
            return b"downloaded"

        async def get_file_info(self, path, request_timeout=None):
            self.info_calls.append((path, request_timeout))
            if path == "/missing":
                raise DaytonaFileNotFoundError("missing path")
            is_dir = path == "/repo"
            return SimpleNamespace(
                path=path,
                name=PurePosixPath(path).name,
                is_dir=is_dir,
                mode="drwxr-xr-x" if is_dir else "-rw-r--r--",
                permissions="0755" if is_dir else "0644",
                size=0 if is_dir else 10,
            )

        async def download_files(self, requests, timeout=1800):
            return [
                SimpleNamespace(source=request.source, result=request.destination, error=None)
                for request in requests
            ]

        async def list_files(self, path, depth=None):
            return [
                SimpleNamespace(
                    path=f"{path}/tool.py",
                    is_dir=False,
                    mode="-rwxr-xr-x",
                    permissions="0755",
                    size=12,
                ),
            ]

    class SdkSandbox:
        def __init__(self, sandbox_id, labels):
            self.id = sandbox_id
            self.labels = labels
            self.process = SdkProcess()
            self.fs = SdkFs()
            self.snapshot_calls = []

        async def create_snapshot(self, name, timeout=60):
            self.snapshot_calls.append((name, timeout))

    class SnapshotService:
        def __init__(self):
            self.deleted = []

        async def get(self, name):
            return SimpleNamespace(id="snap-1", name=name, ref=f"ref/{name}")

        async def delete(self, snapshot):
            self.deleted.append(snapshot)

    class SdkClient:
        def __init__(self):
            self.created = []
            self.sandboxes = {}
            self.snapshot = SnapshotService()
            self.deleted = []
            self.list_query = None
            self.closed = False

        async def create(self, params, *, timeout=60, on_snapshot_create_logs=None):
            self.created.append((params, timeout))
            sandbox = SdkSandbox(f"sdk-{len(self.created)}", params.labels)
            self.sandboxes[sandbox.id] = sandbox
            return sandbox

        async def get(self, sandbox_id):
            return self.sandboxes[sandbox_id]

        def list(self, query=None, request_timeout=None):
            self.list_query = query

            async def iterate():
                for sandbox in self.sandboxes.values():
                    if all(sandbox.labels.get(key) == value for key, value in query.labels.items()):
                        yield sandbox

            return iterate()

        async def delete(self, sandbox, timeout=60, wait=False):
            self.deleted.append((sandbox.id, timeout, wait))
            self.sandboxes.pop(sandbox.id, None)

        async def close(self):
            self.closed = True

    client = SdkClient()
    adapter = module.AsyncDaytonaApi(client)
    resources = module.DaytonaResources(cpu=2, memory=2, disk=5)

    sandbox = await adapter.create_from_image(
        "example:1",
        resources=resources,
        labels={"receipts_run": "run-1"},
        auto_stop_minutes=15,
        ttl_minutes=180,
        timeout_s=900,
    )
    image_params, create_timeout = client.created[0]
    assert image_params.image == "example:1"
    assert image_params.resources.cpu == 2
    assert image_params.resources.memory == 2
    assert image_params.resources.disk == 5
    assert image_params.labels == {"receipts_run": "run-1"}
    assert image_params.auto_stop_interval == 15 and image_params.ttl_minutes == 180
    assert create_timeout == 900

    result = await adapter.exec(sandbox.id, "exit 7", cwd="/repo", timeout_s=11)
    assert result == module.DaytonaCommandResult(exit_code=7, output="merged output")
    assert client.sandboxes[sandbox.id].process.calls == [("exit 7", "/repo", None, 11)]
    client.sandboxes[sandbox.id].process.timeout = True
    with pytest.raises(module.DaytonaCommandTimeout):
        await adapter.exec(sandbox.id, "sleep", cwd="/repo", timeout_s=1)

    await adapter.upload_file(sandbox.id, b"data", "/repo/data", timeout_s=9)
    assert await adapter.get_file_info(
        sandbox.id,
        "/repo/data",
        timeout_s=9,
    ) == module.DaytonaFile(
        path="/repo/data",
        is_dir=False,
        mode="-rw-r--r--",
        permissions="0644",
        size=10,
    )
    assert await adapter.get_file_info(
        sandbox.id,
        "/repo",
        timeout_s=9,
    ) == module.DaytonaFile(
        path="/repo",
        is_dir=True,
        mode="drwxr-xr-x",
        permissions="0755",
        size=0,
    )
    assert await adapter.get_file_info(sandbox.id, "/missing", timeout_s=9) is None
    assert await adapter.download_file(sandbox.id, "/repo/data", timeout_s=9) == b"downloaded"
    assert client.sandboxes[sandbox.id].fs.info_calls == [
        ("/repo/data", 9),
        ("/repo", 9),
        ("/missing", 9),
    ]
    assert client.sandboxes[sandbox.id].fs.downloads == [("/repo/data", 9)]
    request = module.DaytonaDownloadRequest("/repo/data", str(tmp_path / "data"))
    downloads = await adapter.download_files(sandbox.id, [request], timeout_s=9)
    assert downloads[0].source == "/repo/data" and downloads[0].error is None
    files = await adapter.list_files(sandbox.id, "/repo", depth=64)
    assert files == [
        module.DaytonaFile(
            path="/repo/tool.py",
            is_dir=False,
            mode="-rwxr-xr-x",
            permissions="0755",
            size=12,
        ),
    ]

    snapshot = await adapter.create_snapshot(sandbox.id, "checkpoint", timeout_s=900)
    assert snapshot.ref == "ref/checkpoint"
    assert client.sandboxes[sandbox.id].snapshot_calls == [("checkpoint", 900)]
    fork = await adapter.create_from_snapshot(
        "checkpoint",
        labels={"receipts_run": "run-1", "receipts_branch": "b1"},
        auto_stop_minutes=15,
        ttl_minutes=None,
        timeout_s=300,
    )
    snapshot_params, _ = client.created[1]
    assert snapshot_params.snapshot == "checkpoint" and fork.id == "sdk-2"
    listed = await adapter.list_sandboxes({"receipts_run": "run-1"})
    assert {item.id for item in listed} == {"sdk-1", "sdk-2"}
    assert client.list_query.labels == {"receipts_run": "run-1"}
    await adapter.delete_sandbox(fork.id, timeout_s=120)
    assert client.deleted == [("sdk-2", 120, True)]
    await adapter.delete_snapshot(snapshot.id, timeout_s=120)
    assert client.snapshot.deleted == [snapshot.id]
    await adapter.close()
    assert client.closed is True


def test_tree_digest_ignores_git_file_and_tracks_content_and_exec_mode(tmp_path):
    module = _daytona_module()
    tree = tmp_path / "tree"
    tree.mkdir()
    git_pointer = tree / ".git"
    git_pointer.write_text("gitdir: /first\n")
    source = tree / "tool.py"
    source.write_text("VALUE = 1\n")

    initial = module._tree_digest(tree)
    git_pointer.write_text("gitdir: /second\n")
    git_changed = module._tree_digest(tree)
    source.write_text("VALUE = 2\n")
    content_changed = module._tree_digest(tree)
    source.chmod(0o755)
    mode_changed = module._tree_digest(tree)

    assert git_changed == initial
    assert content_changed != initial
    assert mode_changed != content_changed


async def test_digest_download_skips_every_git_path_without_changing_digest(tmp_path):
    module = _daytona_module()
    repository = tmp_path / "repository"
    (repository / ".git" / "objects").mkdir(parents=True)
    (repository / ".git" / "objects" / "large.pack").write_bytes(b"x" * 100_000)
    (repository / "pkg" / "vendor" / ".git").mkdir(parents=True)
    (repository / "pkg" / "vendor" / ".git" / "index").write_bytes(b"nested")
    (repository / "pkg" / "module.py").write_text("VALUE = 1\n")
    expected_digest = module._tree_digest(repository)
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    api.replace_tree("sandbox-1", repository)

    receipt = await executor.run_pytest(base, "tests", timeout_s=30)

    relative_downloads = [
        PurePosixPath(path).relative_to("/repo")
        for path in api.download_calls
    ]
    # One recursive listing of the worktree per download, never one per directory.
    assert api.list_calls and all(
        path == "/repo" and depth == 64 for _, path, depth in api.list_calls
    )
    assert all(".git" not in path.parts for path in relative_downloads)
    assert relative_downloads
    assert receipt.tree_digest == expected_digest


@pytest.mark.live
async def test_live_daytona_prepare_checkpoint_fork_isolation_and_cleanup(tmp_path):
    api_key = os.environ.get("DAYTONA_API_KEY")
    if os.environ.get("RECEIPTS_LIVE") != "1" or not api_key:
        pytest.skip("set RECEIPTS_LIVE=1 and DAYTONA_API_KEY to run Daytona live")

    module = _daytona_module()
    from daytona import AsyncDaytona, DaytonaConfig

    client = AsyncDaytona(DaytonaConfig(api_key=api_key))
    api = module.AsyncDaytonaApi(client)
    executor = module.DaytonaExecutor(
        tmp_path / "executor",
        MemorySink(),
        f"live-{uuid.uuid4().hex[:12]}",
        api,
        ttl_minutes=30,
    )
    try:
        base = await executor.prepare(
            ImageSource(image="python:3.12-slim", workdir="/srv", python="python"),
        )
        checkpoint = await executor.checkpoint(base)
        first, second = await executor.fork(checkpoint, 2)
        await executor.write_file(first, "receipts-only-first.txt", "first\n")
        assert await executor.read_file(first, "receipts-only-first.txt", 100) == "first\n"
        assert await executor.read_file(second, "receipts-only-first.txt", 100) == ""
    finally:
        await executor.close()


async def test_async_daytona_adapter_treats_an_already_deleted_sandbox_as_deleted():
    module = _daytona_module()
    from daytona import DaytonaNotFoundError

    class GoneOnGet:
        async def get(self, sandbox_id):
            raise DaytonaNotFoundError(f"Sandbox with ID or name {sandbox_id} not found")

    class GoneOnDelete:
        async def get(self, sandbox_id):
            return object()

        async def delete(self, sandbox, timeout=60, wait=False):
            raise DaytonaNotFoundError("Failed to remove sandbox: not found")

    await module.AsyncDaytonaApi(GoneOnGet()).delete_sandbox("sandbox-9", timeout_s=5)
    await module.AsyncDaytonaApi(GoneOnDelete()).delete_sandbox("sandbox-9", timeout_s=5)


async def test_patch_digest_matches_the_digest_recorded_for_test_runs_with_symlinks(tmp_path):
    """The claim audit compares the patch receipt's tree digest with the digest a
    test run recorded; both must hash the same view of the tree, symlinks included."""
    module = _daytona_module()
    repository = tmp_path / "repository"
    snapshot_sha = _symlink_repository(repository)
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    api.replace_tree("sandbox-1", repository)
    api.snapshot_sha = snapshot_sha
    snapshot = await executor.snapshot(base)
    checkpoint = await executor.checkpoint(base)
    (agent,) = await executor.fork(checkpoint, 1, prefix="agent")
    api.set_file(executor._sandboxes[agent.id], "/repo/unrelated.txt", b"unrelated after\n")

    tested_digest = await executor._tree_digest(agent)
    receipt = await executor.patch(agent, snapshot.snapshot_sha)

    assert receipt.exit_code == 0
    assert receipt.tree_digest == tested_digest


async def test_command_duration_ignores_wall_clock_jumps_such_as_host_sleep(tmp_path, monkeypatch):
    """Durations decide the baseline time limit; a host that sleeps mid-command makes the
    wall clock jump, so durations must come from a monotonic clock."""
    from datetime import datetime, timedelta, timezone

    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
    base = await executor.prepare(ImageSource(image="example:1", workdir="/repo"))
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    ticks = iter([start, start + timedelta(seconds=1000)] * 10)
    monkeypatch.setattr(module, "_now", lambda: next(ticks))

    receipt = await executor.run(base, "true", timeout_s=30)

    assert receipt.duration_s < 60


def test_default_auto_stop_outlasts_a_long_witness_phase(tmp_path):
    """Seen on qiskit-12528: the agent sandbox idles while the witness is forked, patched
    and tested, which took over 13 minutes on a large repository, and a 15-minute idle
    auto-stop stopped it before the appeal. The default must outlast that phase."""
    module = _daytona_module()
    executor, _, _ = _executor(tmp_path, module)

    assert executor.auto_stop_minutes >= 60
