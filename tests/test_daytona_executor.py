import hashlib
import importlib
import logging
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from receipts.models import Branch
from receipts.sandbox.protocol import CheckpointTampered, ImageSource
from receipts.sandbox.sink import MemorySink


def _daytona_module():
    try:
        return importlib.import_module("receipts.sandbox.daytona")
    except ModuleNotFoundError:
        pytest.fail("the Daytona executor module is not implemented")


class MemoryDaytonaApi:
    """In-memory Daytona fake. No method reaches the network or a local shell."""

    def __init__(self, module):
        self.module = module
        self.sandboxes = {}
        self.snapshots = {}
        self.create_calls = []
        self.exec_calls = []
        self.upload_calls = []
        self.deleted_sandboxes = []
        self.deleted_snapshots = []
        self.timeout_commands = set()
        self.command_results = {}
        self.snapshot_delete_status = None
        self.closed = False
        self._sandbox_number = 0
        self._snapshot_number = 0

    def _new_sandbox(self, labels, files=None):
        self._sandbox_number += 1
        sandbox_id = f"sandbox-{self._sandbox_number}"
        self.sandboxes[sandbox_id] = {
            "labels": dict(labels),
            "files": deepcopy(files or {}),
        }
        return self.module.DaytonaSandbox(id=sandbox_id)

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
        return self._new_sandbox(labels, {"/repo/original.txt": b"original\n"})

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
        return self._new_sandbox(labels, self.snapshots[snapshot]["files"])

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
        if "git rev-parse HEAD" in command:
            return self.module.DaytonaCommandResult(exit_code=0, output="a" * 40 + "\n")
        return self.module.DaytonaCommandResult(exit_code=0, output=f"ran:{command}")

    async def upload_file(self, sandbox_id, content, remote_path, *, timeout_s):
        self.upload_calls.append((sandbox_id, content, remote_path, timeout_s))
        self.sandboxes[sandbox_id]["files"][remote_path] = bytes(content)

    async def download_file(self, sandbox_id, remote_path, *, timeout_s):
        return self.sandboxes[sandbox_id]["files"].get(remote_path)

    async def download_files(self, sandbox_id, requests, *, timeout_s):
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
                    Path(request.destination).write_bytes(content)
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
        prefix = path.rstrip("/") + "/"
        return [
            self.module.DaytonaFile(
                path=file_path,
                is_dir=False,
                mode="-rw-r--r--",
                permissions="0644",
                size=len(content),
            )
            for file_path, content in self.sandboxes[sandbox_id]["files"].items()
            if file_path.startswith(prefix)
        ]

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
            "auto_stop_minutes": 15,
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


async def test_close_deletes_tracked_and_label_swept_sandboxes_and_logs_snapshot_403(
    tmp_path,
    caplog,
):
    module = _daytona_module()
    executor, api, _ = _executor(tmp_path, module)
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

    with caplog.at_level(logging.WARNING):
        await executor.close()

    assert set(api.deleted_sandboxes) == {"sandbox-1", "sandbox-2", orphan.id}
    assert foreign.id in api.sandboxes
    assert len(api.deleted_snapshots) == 1
    assert "403" in caplog.text and "snapshot" in caplog.text
    assert api.closed is True
    await executor.close()
    assert len(api.deleted_snapshots) == 1


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
    from daytona import DaytonaProcessExecutionTimeoutError

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

        async def upload_file(self, content, remote_path, timeout=1800):
            self.uploads.append((content, remote_path, timeout))

        async def download_file(self, remote_path, timeout=1800):
            return b"downloaded"

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
    assert await adapter.download_file(sandbox.id, "/repo/data", timeout_s=9) == b"downloaded"
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
