"""Daytona-backed executor lifecycle and the small API boundary it uses.

The executor owns receipts, sequence numbers, provenance ids, trusted files,
and cleanup. ``AsyncDaytonaApi`` is the only class that knows the SDK object
shape. Unit tests replace that boundary with an in-memory implementation.

Daytona does not create an image for each command. Branch provenance therefore
uses the immutable branch root followed by a local sequence number. A prepared
branch starts at its sandbox id, and a fork starts at its snapshot ref.
"""

from __future__ import annotations

import hashlib
import logging
import posixpath
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Protocol

from daytona import (
    AsyncDaytona,
    CreateSandboxFromImageParams,
    CreateSandboxFromSnapshotParams,
    DaytonaFileNotFoundError,
    DaytonaProcessExecutionTimeoutError,
    FileDownloadRequest,
    ListSandboxesQuery,
    Resources,
)

from receipts.models import Branch, Checkpoint, Receipt
from receipts.sandbox.protocol import (
    PYTEST_BOOTSTRAP,
    CheckpointTampered,
    ImageSource,
    Source,
)
from receipts.sandbox.sink import ReceiptSink

TAIL = 6000
_LOG = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tail(data: bytes) -> str:
    return data.decode(errors="replace")[-TAIL:]


@dataclass(frozen=True)
class DaytonaResources:
    cpu: int = 2
    memory: int = 2
    disk: int = 5


@dataclass(frozen=True)
class DaytonaSandbox:
    id: str


@dataclass(frozen=True)
class DaytonaSnapshot:
    id: str
    name: str
    ref: str


@dataclass(frozen=True)
class DaytonaCommandResult:
    exit_code: int
    output: str


@dataclass(frozen=True)
class DaytonaDownloadRequest:
    source: str
    destination: str | None = None


@dataclass(frozen=True)
class DaytonaDownloadResult:
    source: str
    result: str | bytes | None
    error: str | None


@dataclass(frozen=True)
class DaytonaFile:
    path: str
    is_dir: bool
    mode: str
    permissions: str
    size: int


class DaytonaCommandTimeout(TimeoutError):
    """The sandbox stopped a command after its explicit timeout."""


class DaytonaApi(Protocol):
    async def create_from_image(
        self,
        image: str,
        *,
        resources: DaytonaResources,
        labels: dict[str, str],
        auto_stop_minutes: int,
        ttl_minutes: int | None,
        timeout_s: int,
    ) -> DaytonaSandbox: ...

    async def create_from_snapshot(
        self,
        snapshot: str,
        *,
        labels: dict[str, str],
        auto_stop_minutes: int,
        ttl_minutes: int | None,
        timeout_s: int,
    ) -> DaytonaSandbox: ...

    async def exec(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str,
        timeout_s: int,
        env: dict[str, str] | None = None,
    ) -> DaytonaCommandResult: ...

    async def upload_file(
        self,
        sandbox_id: str,
        content: bytes,
        remote_path: str,
        *,
        timeout_s: int,
    ) -> None: ...

    async def download_file(
        self,
        sandbox_id: str,
        remote_path: str,
        *,
        timeout_s: int,
    ) -> bytes | None: ...

    async def download_files(
        self,
        sandbox_id: str,
        requests: list[DaytonaDownloadRequest],
        *,
        timeout_s: int,
    ) -> list[DaytonaDownloadResult]: ...

    async def list_files(
        self,
        sandbox_id: str,
        path: str,
        *,
        depth: int,
    ) -> list[DaytonaFile]: ...

    async def create_snapshot(
        self,
        sandbox_id: str,
        name: str,
        *,
        timeout_s: int,
    ) -> DaytonaSnapshot: ...

    async def get_snapshot(self, name: str) -> DaytonaSnapshot: ...

    async def list_sandboxes(self, labels: dict[str, str]) -> list[DaytonaSandbox]: ...

    async def delete_sandbox(self, sandbox_id: str, *, timeout_s: int) -> None: ...

    async def delete_snapshot(self, snapshot: str, *, timeout_s: int) -> None: ...

    async def close(self) -> None: ...


class AsyncDaytonaApi:
    """Adapter from the narrow executor boundary to ``AsyncDaytona``."""

    def __init__(self, client: AsyncDaytona) -> None:
        self.client = client
        self._sandboxes: dict[str, object] = {}

    async def _sandbox(self, sandbox_id: str):
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            sandbox = await self.client.get(sandbox_id)
            self._sandboxes[sandbox_id] = sandbox
        return sandbox

    async def create_from_image(
        self,
        image: str,
        *,
        resources: DaytonaResources,
        labels: dict[str, str],
        auto_stop_minutes: int,
        ttl_minutes: int | None,
        timeout_s: int,
    ) -> DaytonaSandbox:
        params = CreateSandboxFromImageParams(
            image=image,
            resources=Resources(
                cpu=resources.cpu,
                memory=resources.memory,
                disk=resources.disk,
            ),
            labels=dict(labels),
            auto_stop_interval=auto_stop_minutes,
            ttl_minutes=ttl_minutes,
        )
        sandbox = await self.client.create(params, timeout=timeout_s)
        self._sandboxes[sandbox.id] = sandbox
        return DaytonaSandbox(id=sandbox.id)

    async def create_from_snapshot(
        self,
        snapshot: str,
        *,
        labels: dict[str, str],
        auto_stop_minutes: int,
        ttl_minutes: int | None,
        timeout_s: int,
    ) -> DaytonaSandbox:
        params = CreateSandboxFromSnapshotParams(
            snapshot=snapshot,
            labels=dict(labels),
            auto_stop_interval=auto_stop_minutes,
            ttl_minutes=ttl_minutes,
        )
        sandbox = await self.client.create(params, timeout=timeout_s)
        self._sandboxes[sandbox.id] = sandbox
        return DaytonaSandbox(id=sandbox.id)

    async def exec(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str,
        timeout_s: int,
        env: dict[str, str] | None = None,
    ) -> DaytonaCommandResult:
        sandbox = await self._sandbox(sandbox_id)
        try:
            result = await sandbox.process.exec(
                command,
                cwd=cwd,
                env=env,
                timeout=timeout_s,
            )
        except DaytonaProcessExecutionTimeoutError as exc:
            raise DaytonaCommandTimeout(command) from exc
        return DaytonaCommandResult(exit_code=result.exit_code, output=result.result)

    async def upload_file(
        self,
        sandbox_id: str,
        content: bytes,
        remote_path: str,
        *,
        timeout_s: int,
    ) -> None:
        sandbox = await self._sandbox(sandbox_id)
        await sandbox.fs.upload_file(content, remote_path, timeout=timeout_s)

    async def download_file(
        self,
        sandbox_id: str,
        remote_path: str,
        *,
        timeout_s: int,
    ) -> bytes | None:
        sandbox = await self._sandbox(sandbox_id)
        try:
            return await sandbox.fs.download_file(remote_path, timeout_s)
        except DaytonaFileNotFoundError:
            return None

    async def download_files(
        self,
        sandbox_id: str,
        requests: list[DaytonaDownloadRequest],
        *,
        timeout_s: int,
    ) -> list[DaytonaDownloadResult]:
        sandbox = await self._sandbox(sandbox_id)
        sdk_requests = [
            FileDownloadRequest(
                source=request.source,
                destination=request.destination,
            )
            for request in requests
        ]
        responses = await sandbox.fs.download_files(sdk_requests, timeout=timeout_s)
        return [
            DaytonaDownloadResult(
                source=response.source,
                result=response.result,
                error=response.error,
            )
            for response in responses
        ]

    async def list_files(
        self,
        sandbox_id: str,
        path: str,
        *,
        depth: int,
    ) -> list[DaytonaFile]:
        sandbox = await self._sandbox(sandbox_id)
        entries = await sandbox.fs.list_files(path, depth=depth)
        return [
            DaytonaFile(
                path=entry.path or posixpath.join(path, entry.name),
                is_dir=entry.is_dir,
                mode=entry.mode,
                permissions=entry.permissions,
                size=entry.size,
            )
            for entry in entries
        ]

    async def create_snapshot(
        self,
        sandbox_id: str,
        name: str,
        *,
        timeout_s: int,
    ) -> DaytonaSnapshot:
        sandbox = await self._sandbox(sandbox_id)
        await sandbox.create_snapshot(name, timeout=timeout_s)
        return await self.get_snapshot(name)

    async def get_snapshot(self, name: str) -> DaytonaSnapshot:
        snapshot = await self.client.snapshot.get(name)
        return DaytonaSnapshot(id=snapshot.id, name=snapshot.name, ref=snapshot.ref)

    async def list_sandboxes(self, labels: dict[str, str]) -> list[DaytonaSandbox]:
        sandboxes: list[DaytonaSandbox] = []
        async for sandbox in self.client.list(ListSandboxesQuery(labels=dict(labels))):
            self._sandboxes[sandbox.id] = sandbox
            sandboxes.append(DaytonaSandbox(id=sandbox.id))
        return sandboxes

    async def delete_sandbox(self, sandbox_id: str, *, timeout_s: int) -> None:
        sandbox = await self._sandbox(sandbox_id)
        await self.client.delete(sandbox, timeout=timeout_s, wait=True)
        self._sandboxes.pop(sandbox_id, None)

    async def delete_snapshot(self, snapshot: str, *, timeout_s: int) -> None:
        del timeout_s
        await self.client.snapshot.delete(snapshot)

    async def close(self) -> None:
        await self.client.close()


@dataclass(frozen=True)
class _BranchSpec:
    workdir: str
    python: str


class DaytonaExecutor:
    def __init__(
        self,
        root: Path,
        sink: ReceiptSink,
        run_id: str,
        api: DaytonaApi,
        *,
        resources: DaytonaResources | None = None,
        auto_stop_minutes: int = 15,
        ttl_minutes: int | None = None,
        create_timeout_s: int = 900,
        fork_timeout_s: int = 300,
        snapshot_timeout_s: int = 900,
        file_timeout_s: int = 120,
    ) -> None:
        self.root = root
        self.sink = sink
        self.run_id = run_id
        self.api = api
        self.resources = resources or DaytonaResources()
        self.auto_stop_minutes = auto_stop_minutes
        self.ttl_minutes = ttl_minutes
        self.create_timeout_s = create_timeout_s
        self.fork_timeout_s = fork_timeout_s
        self.snapshot_timeout_s = snapshot_timeout_s
        self.file_timeout_s = file_timeout_s
        self._validate_configuration()

        self._seq: dict[str, int] = {}
        self._roots: dict[str, str] = {}
        self._sandboxes: dict[str, str] = {}
        self._specs: dict[str, _BranchSpec] = {}
        self._created_sandboxes: list[str] = []
        self._snapshots: dict[str, DaytonaSnapshot] = {}
        self._snapshot_specs: dict[str, _BranchSpec] = {}
        self._fork_next: dict[str, int] = {}
        self._closed = False

        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(exist_ok=True)
        (self.root / "reports").mkdir(exist_ok=True)
        (self.root / "patches").mkdir(exist_ok=True)
        (self.root / "staging").mkdir(exist_ok=True)

    def _validate_configuration(self) -> None:
        if min(self.resources.cpu, self.resources.memory, self.resources.disk) <= 0:
            raise ValueError("Daytona resources must be positive")
        if self.auto_stop_minutes < 0:
            raise ValueError("auto_stop_minutes must be non-negative")
        if self.ttl_minutes is not None and self.ttl_minutes < 0:
            raise ValueError("ttl_minutes must be non-negative")
        for value in (
            self.create_timeout_s,
            self.fork_timeout_s,
            self.snapshot_timeout_s,
            self.file_timeout_s,
        ):
            if value <= 0:
                raise ValueError("Daytona operation timeouts must be positive")

    async def __aenter__(self) -> DaytonaExecutor:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

    @staticmethod
    def _validate_workdir(workdir: str) -> str:
        path = PurePosixPath(workdir)
        if not path.is_absolute() or posixpath.normpath(workdir) != workdir:
            raise ValueError(f"Daytona workdir must be a normalized absolute path: {workdir}")
        return workdir

    @staticmethod
    def _path_parts(path: str) -> tuple[str, ...] | None:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            return None
        normalized = posixpath.normpath(path)
        if normalized in ("", ".") or normalized.startswith("../"):
            return None
        return PurePosixPath(normalized).parts

    def _labels(self, branch_id: str) -> dict[str, str]:
        return {
            "receipts_run": self.run_id,
            "receipts_branch": branch_id,
        }

    def _sandbox_id(self, branch: Branch) -> str:
        try:
            return self._sandboxes[branch.id]
        except KeyError as exc:
            raise RuntimeError(f"unknown Daytona branch: {branch.id}") from exc

    def _spec(self, branch: Branch) -> _BranchSpec:
        try:
            return self._specs[branch.id]
        except KeyError as exc:
            raise RuntimeError(f"unknown Daytona branch: {branch.id}") from exc

    def _remote_path(self, branch: Branch, parts: tuple[str, ...]) -> str:
        return posixpath.join(self._spec(branch).workdir, *parts)

    def _emit(self, branch: Branch, **fields) -> Receipt:
        seq = self._seq.get(branch.id, 0) + 1
        self._seq[branch.id] = seq
        before = branch.head
        after = f"{self._roots[branch.id]}#{seq}"
        branch.head = after
        receipt = Receipt(
            receipt_id=f"{branch.id}-{seq}",
            seq=seq,
            branch_id=branch.id,
            image_before=before,
            image_after=after,
            **fields,
        )
        self.sink.write(receipt)
        return receipt

    def _write_log(self, branch: Branch, output: bytes) -> Path:
        seq = self._seq.get(branch.id, 0) + 1
        path = self.root / "logs" / f"{branch.id}-{seq}.log"
        path.write_bytes(output)
        return path

    async def _execute(
        self,
        branch: Branch,
        command: str,
        timeout_s: int,
        env: dict[str, str] | None = None,
    ) -> tuple[bytes, int | None, bool, datetime, float]:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        started = _now()
        try:
            result = await self.api.exec(
                self._sandbox_id(branch),
                command,
                cwd=self._spec(branch).workdir,
                timeout_s=timeout_s,
                env=env,
            )
        except DaytonaCommandTimeout:
            output = b""
            exit_code = None
            timed_out = True
        else:
            output = result.output.encode()
            exit_code = result.exit_code
            timed_out = False
        return output, exit_code, timed_out, started, (_now() - started).total_seconds()

    async def prepare(self, source: Source) -> Branch:
        if self._sandboxes:
            raise RuntimeError("DaytonaExecutor.prepare may only be called once")
        if not isinstance(source, ImageSource):
            raise TypeError("DaytonaExecutor requires an ImageSource")
        spec = _BranchSpec(
            workdir=self._validate_workdir(source.workdir),
            python=source.python,
        )
        sandbox = await self.api.create_from_image(
            source.image,
            resources=self.resources,
            labels=self._labels("base"),
            auto_stop_minutes=self.auto_stop_minutes,
            ttl_minutes=self.ttl_minutes,
            timeout_s=self.create_timeout_s,
        )
        self._created_sandboxes.append(sandbox.id)
        branch = Branch(
            id="base",
            run_id=self.run_id,
            head=sandbox.id,
            origin=sandbox.id,
        )
        self._sandboxes[branch.id] = sandbox.id
        self._specs[branch.id] = spec
        self._roots[branch.id] = sandbox.id

        try:
            prepared = await self.api.exec(
                sandbox.id,
                "mkdir -p /opt/receipts/reports",
                cwd="/",
                timeout_s=self.file_timeout_s,
            )
        except DaytonaCommandTimeout as exc:
            raise RuntimeError("trusted bootstrap directory creation timed out") from exc
        if prepared.exit_code != 0:
            raise RuntimeError(
                f"trusted bootstrap directory creation failed (exit {prepared.exit_code}): "
                f"{prepared.output[-500:]}",
            )
        await self.api.upload_file(
            sandbox.id,
            PYTEST_BOOTSTRAP.encode(),
            "/opt/receipts/receipts_pytest.py",
            timeout_s=self.file_timeout_s,
        )

        for command in source.setup:
            receipt = await self.run(branch, command, timeout_s=1800)
            if receipt.timed_out or receipt.exit_code != 0:
                raise RuntimeError(
                    f"setup command failed (exit {receipt.exit_code}, "
                    f"timed_out={receipt.timed_out}): {receipt.stdout_tail[-500:]}",
                )
        return branch

    async def run(self, branch: Branch, cmd: str, timeout_s: int) -> Receipt:
        output, code, timed_out, started, duration = await self._execute(
            branch,
            cmd,
            timeout_s,
        )
        log_path = self._write_log(branch, output)
        return self._emit(
            branch,
            kind="command",
            cmd=cmd,
            exit_code=code,
            stdout_tail=_tail(output),
            stderr_tail="",
            stdout_sha256=hashlib.sha256(output).hexdigest(),
            log_path=str(log_path),
            started_at=started,
            duration_s=duration,
            timed_out=timed_out,
        )

    async def read_file(self, branch: Branch, path: str, max_bytes: int) -> str:
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        parts = self._path_parts(path)
        if parts is None:
            return ""
        content = await self.api.download_file(
            self._sandbox_id(branch),
            self._remote_path(branch, parts),
            timeout_s=self.file_timeout_s,
        )
        if content is None:
            return ""
        return content[:max_bytes].decode(errors="replace")

    async def write_file(self, branch: Branch, path: str, content: str) -> Receipt:
        started = _now()
        parts = self._path_parts(path)
        if parts is None:
            return self._emit(
                branch,
                kind="write",
                path=path,
                exit_code=1,
                stderr_tail="refused: path is outside the repository",
                started_at=started,
                duration_s=(_now() - started).total_seconds(),
            )
        encoded = content.encode()
        await self.api.upload_file(
            self._sandbox_id(branch),
            encoded,
            self._remote_path(branch, parts),
            timeout_s=self.file_timeout_s,
        )
        return self._emit(
            branch,
            kind="write",
            path=path,
            exit_code=0,
            stdout_sha256=hashlib.sha256(encoded).hexdigest(),
            started_at=started,
            duration_s=(_now() - started).total_seconds(),
        )

    async def snapshot(self, branch: Branch) -> Receipt:
        command = (
            "git add -A && git -c user.name=receipts "
            "-c user.email=receipts@localhost commit -q --allow-empty "
            "-m \"receipts snapshot\" && git rev-parse HEAD"
        )
        output, code, timed_out, started, duration = await self._execute(
            branch,
            command,
            120,
        )
        snapshot_sha = None
        if code == 0:
            lines = output.decode(errors="replace").splitlines()
            snapshot_sha = lines[-1].strip() if lines else None
        log_path = self._write_log(branch, output)
        return self._emit(
            branch,
            kind="command",
            cmd=command,
            exit_code=code,
            stdout_tail=_tail(output),
            stderr_tail="",
            stdout_sha256=hashlib.sha256(output).hexdigest(),
            log_path=str(log_path),
            started_at=started,
            duration_s=duration,
            timed_out=timed_out,
            snapshot_sha=snapshot_sha,
        )

    def _snapshot_name(self) -> str:
        safe_run = re.sub(r"[^A-Za-z0-9-]+", "-", self.run_id).strip("-")
        safe_run = (safe_run or "run")[:40]
        return f"receipts-{safe_run}-{uuid.uuid4().hex[:12]}"

    async def checkpoint(self, branch: Branch) -> Checkpoint:
        sandbox_id = self._sandbox_id(branch)
        snapshot = await self.api.create_snapshot(
            sandbox_id,
            self._snapshot_name(),
            timeout_s=self.snapshot_timeout_s,
        )
        if not snapshot.ref:
            raise RuntimeError("Daytona returned a snapshot without a ref")
        self._snapshots[snapshot.ref] = snapshot
        self._snapshot_specs[snapshot.ref] = self._spec(branch)
        return Checkpoint(id=snapshot.ref, parent=branch.head, digest=snapshot.ref)

    async def fork(
        self,
        checkpoint: Checkpoint,
        n: int,
        prefix: str = "b",
    ) -> list[Branch]:
        if n < 0:
            raise ValueError("n must be non-negative")
        if checkpoint.id != checkpoint.digest:
            raise CheckpointTampered(checkpoint.id)
        snapshot = self._snapshots.get(checkpoint.id)
        spec = self._snapshot_specs.get(checkpoint.id)
        if snapshot is None or spec is None:
            raise CheckpointTampered(checkpoint.id)
        current = await self.api.get_snapshot(snapshot.name)
        if current.ref != checkpoint.id:
            raise CheckpointTampered(checkpoint.id)

        branches: list[Branch] = []
        next_index = self._fork_next.get(prefix, 1)
        for index in range(next_index, next_index + n):
            branch_id = f"{prefix}{index}"
            sandbox = await self.api.create_from_snapshot(
                snapshot.name,
                labels=self._labels(branch_id),
                auto_stop_minutes=self.auto_stop_minutes,
                ttl_minutes=self.ttl_minutes,
                timeout_s=self.fork_timeout_s,
            )
            self._created_sandboxes.append(sandbox.id)
            branch = Branch(
                id=branch_id,
                run_id=self.run_id,
                head=checkpoint.id,
                origin=checkpoint.id,
            )
            self._sandboxes[branch.id] = sandbox.id
            self._specs[branch.id] = spec
            self._roots[branch.id] = checkpoint.id
            branches.append(branch)
            self._fork_next[prefix] = index + 1
        return branches

    @staticmethod
    def _status_code(exc: BaseException) -> int | None:
        value = getattr(exc, "status_code", None)
        return value if isinstance(value, int) else None

    async def close(self) -> None:
        if self._closed:
            return
        failures: dict[str, str] = {}
        deleted: set[str] = set()

        async def delete_sandbox(sandbox_id: str) -> None:
            try:
                await self.api.delete_sandbox(sandbox_id, timeout_s=120)
            except Exception as exc:  # Cleanup must continue after one provider failure.
                failures[f"sandbox {sandbox_id}"] = str(exc)
            else:
                failures.pop(f"sandbox {sandbox_id}", None)
                deleted.add(sandbox_id)

        for sandbox_id in reversed(list(dict.fromkeys(self._created_sandboxes))):
            await delete_sandbox(sandbox_id)

        try:
            swept = await self.api.list_sandboxes({"receipts_run": self.run_id})
        except Exception as exc:  # Cleanup must still attempt snapshot deletion.
            failures["sandbox label sweep"] = str(exc)
        else:
            for sandbox in swept:
                await delete_sandbox(sandbox.id)

        retained_snapshot_refs: set[str] = set()
        for snapshot_ref, snapshot in list(self._snapshots.items()):
            try:
                await self.api.delete_snapshot(snapshot.id, timeout_s=120)
            except Exception as exc:  # A known key scope gap must not hide sandbox cleanup.
                if self._status_code(exc) == 403:
                    _LOG.warning(
                        "Daytona snapshot deletion returned 403 for %s: %s",
                        snapshot.id,
                        exc,
                    )
                else:
                    failures[f"snapshot {snapshot.id}"] = str(exc)
                    retained_snapshot_refs.add(snapshot_ref)

        if deleted:
            self._created_sandboxes = [
                sandbox_id
                for sandbox_id in self._created_sandboxes
                if sandbox_id not in deleted
            ]
            removed_branches = {
                branch_id
                for branch_id, sandbox_id in self._sandboxes.items()
                if sandbox_id in deleted
            }
            for branch_id in removed_branches:
                self._sandboxes.pop(branch_id, None)
                self._specs.pop(branch_id, None)
                self._roots.pop(branch_id, None)
        self._snapshots = {
            snapshot_ref: snapshot
            for snapshot_ref, snapshot in self._snapshots.items()
            if snapshot_ref in retained_snapshot_refs
        }
        self._snapshot_specs = {
            snapshot_ref: spec
            for snapshot_ref, spec in self._snapshot_specs.items()
            if snapshot_ref in retained_snapshot_refs
        }

        if failures:
            detail = "; ".join(f"{name}: {error}" for name, error in failures.items())
            raise RuntimeError("failed to clean up Daytona resources: " + detail)

        await self.api.close()
        self._closed = True
