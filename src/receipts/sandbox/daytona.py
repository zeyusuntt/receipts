"""Daytona-backed executor lifecycle and the small API boundary it uses.

The executor owns receipts, sequence numbers, provenance ids, trusted files,
and cleanup. ``AsyncDaytonaApi`` is the only class that knows the SDK object
shape. Unit tests replace that boundary with an in-memory implementation.

Daytona does not create an image for each command. Branch provenance therefore
uses the immutable branch root followed by a local sequence number. A prepared
branch starts at its sandbox id, and a fork starts at its snapshot ref.

Daytona downloads file symlinks as regular files, directory symlinks as empty
directories, and omits dangling symlinks. The executor reconstructs checkpoint
symlinks from the trusted Git index and carries them unchanged into patch
staging. Agent changes to a symlink itself are not captured. Changes to the
link's target file are captured through the target file's own path.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import posixpath
import re
import shlex
import shutil
import signal
import stat
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Protocol

from daytona import (
    AsyncDaytona,
    CreateSandboxFromImageParams,
    CreateSandboxFromSnapshotParams,
    DaytonaFileNotFoundError,
    DaytonaNotFoundError,
    DaytonaProcessExecutionTimeoutError,
    FileDownloadRequest,
    ListSandboxesQuery,
    Resources,
)

from receipts.junit import parse_junit
from receipts.models import Branch, Checkpoint, Receipt, ReceiptKind
from receipts.patchscope import default_protected_modules, filter_patch, summarize_patch
from receipts.sandbox.protocol import (
    PYTEST_BOOTSTRAP,
    GIT_APPLY_FLAGS,
    PYTEST_FLAGS,
    CheckpointTampered,
    ImageSource,
    Source,
)
from receipts.sandbox.sink import ReceiptSink
from receipts.sandbox.staging import (
    git_command,
    git_environment,
    mirror_worktree,
    patch_command,
    remove_path,
)

TAIL = 6000
_LOG = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tail(data: bytes) -> str:
    return data.decode(errors="replace")[-TAIL:]


def _tree_digest_ignores(path: str) -> bool:
    return ".git" in PurePosixPath(path).parts


def _skip_top_level_git(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(parts) and parts[0] == ".git"


def _skip_nothing(path: str) -> bool:
    return False


def _tree_digest(root: Path) -> str:
    entries: list[tuple[str, int, str]] = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(root)
        names[:] = sorted(
            name
            for name in names
            if not _tree_digest_ignores((relative_directory / name).as_posix())
        )
        for filename in sorted(
            name
            for name in filenames
            if not _tree_digest_ignores((relative_directory / name).as_posix())
        ):
            path = directory_path / filename
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                content = os.fsencode(os.readlink(path))
            elif stat.S_ISREG(mode):
                content = path.read_bytes()
            else:
                content = b""
            entries.append(
                (
                    path.relative_to(root).as_posix(),
                    stat.S_IMODE(mode),
                    hashlib.sha256(content).hexdigest(),
                ),
            )
    serialized = json.dumps(entries, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _set_symlink(path: Path, target: str) -> None:
    if os.path.lexists(path):
        remove_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)


def _copy_checkpoint_symlinks(
    checkpoint_tree: Path,
    agent_tree: Path,
    symlink_paths: tuple[Path, ...],
) -> None:
    for relative in symlink_paths:
        source = checkpoint_tree / relative
        if not source.is_symlink():
            raise OSError(f"checkpoint symlink is unavailable: {relative.as_posix()}")
        _set_symlink(agent_tree / relative, os.readlink(source))


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
        # A sandbox that is already gone counts as deleted: the live service
        # keeps listing a sandbox while it is torn down.
        try:
            sandbox = await self._sandbox(sandbox_id)
            await self.client.delete(sandbox, timeout=timeout_s, wait=True)
        except DaytonaNotFoundError:
            return
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
        # The agent sandbox idles while a witness is forked, patched and tested; on a large
        # repository that took over 13 minutes, so a 15-minute idle stop killed it mid-run.
        auto_stop_minutes: int = 60,
        ttl_minutes: int | None = None,
        create_timeout_s: int = 900,
        fork_timeout_s: int = 300,
        snapshot_timeout_s: int = 900,
        file_timeout_s: int = 120,
        clock: Callable[[], float] = time.monotonic,
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
        self._clock = clock
        self._validate_configuration()

        self._seq: dict[str, int] = {}
        self._roots: dict[str, str] = {}
        self._sandboxes: dict[str, str] = {}
        self._specs: dict[str, _BranchSpec] = {}
        self._created_sandboxes: list[str] = []
        self._sandbox_lifetimes: dict[str, tuple[float, float | None]] = {}
        self._snapshots: dict[str, DaytonaSnapshot] = {}
        self._snapshot_specs: dict[str, _BranchSpec] = {}
        self._checkpoint_trees: dict[str, Path] = {}
        self._checkpoint_symlinks: dict[str, tuple[Path, ...]] = {}
        self._fork_next: dict[str, int] = {}
        self._released_branches: set[str] = set()
        self._closed = False
        self._protected_modules = default_protected_modules()

        git_path = shutil.which("git")
        if git_path is None:
            raise RuntimeError("git executable not found")
        self._git = Path(git_path).resolve()
        bash_path = shutil.which("bash", path=os.defpath)
        if bash_path is None:
            raise RuntimeError("bash executable not found")
        self._bash = Path(bash_path).resolve()

        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(exist_ok=True)
        (self.root / "reports").mkdir(exist_ok=True)
        (self.root / "patches").mkdir(exist_ok=True)
        (self.root / "staging").mkdir(exist_ok=True)
        (self.root / "checkpoints").mkdir(exist_ok=True)

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

    def _record_sandbox_created(self, sandbox_id: str) -> None:
        self._sandbox_lifetimes[sandbox_id] = (self._clock(), None)

    def _record_sandbox_deleted(self, sandbox_id: str) -> None:
        lifetime = self._sandbox_lifetimes.get(sandbox_id)
        if lifetime is None or lifetime[1] is not None:
            return
        self._sandbox_lifetimes[sandbox_id] = (lifetime[0], self._clock())

    def sandbox_usage(self) -> list[dict]:
        """Return measured lifetime and resources for each created sandbox."""

        now = self._clock()
        resources = {
            "cpu": self.resources.cpu,
            "memory": self.resources.memory,
            "disk": self.resources.disk,
        }
        return [
            {
                "sandbox_id": sandbox_id,
                "seconds": max(
                    0.0,
                    (deleted_at if deleted_at is not None else now) - created_at,
                ),
                "resources": dict(resources),
            }
            for sandbox_id, (created_at, deleted_at) in self._sandbox_lifetimes.items()
        ]

    def _sandbox_id(self, branch: Branch) -> str:
        if branch.id in self._released_branches:
            raise RuntimeError(f"released Daytona branch: {branch.id}")
        try:
            return self._sandboxes[branch.id]
        except KeyError as exc:
            raise RuntimeError(f"unknown Daytona branch: {branch.id}") from exc

    def _spec(self, branch: Branch) -> _BranchSpec:
        if branch.id in self._released_branches:
            raise RuntimeError(f"released Daytona branch: {branch.id}")
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
        started_monotonic = time.monotonic()
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
        return output, exit_code, timed_out, started, time.monotonic() - started_monotonic

    def _relative_remote_path(self, branch: Branch, remote_path: str) -> Path | None:
        normalized = PurePosixPath(posixpath.normpath(remote_path))
        workdir = PurePosixPath(self._spec(branch).workdir)
        try:
            relative = normalized.relative_to(workdir)
        except ValueError as exc:
            raise OSError(f"Daytona listed a path outside the repository: {remote_path}") from exc
        if not relative.parts:
            return None
        if any(part in ("", ".", "..") for part in relative.parts):
            raise OSError(f"Daytona listed an invalid repository path: {remote_path}")
        return Path(*relative.parts)

    async def _download_tree(
        self,
        branch: Branch,
        destination: Path,
        *,
        skip: Callable[[str], bool],
    ) -> float:
        if destination.exists():
            await asyncio.to_thread(remove_path, destination)
        destination.mkdir(parents=True)
        started = time.monotonic()
        files: list[tuple[DaytonaFile, Path]] = []
        seen: set[Path] = set()
        # One recursive listing, as before: a listing per directory would cost a
        # round trip per directory on every digest. Skipped paths are listed but
        # never downloaded, which is where the time went.
        entries = await self.api.list_files(
            self._sandbox_id(branch),
            self._spec(branch).workdir,
            depth=64,
        )
        for entry in entries:
            relative = self._relative_remote_path(branch, entry.path)
            if relative is None:
                continue
            if skip(relative.as_posix()):
                continue
            if relative in seen:
                raise OSError(
                    f"Daytona listed a duplicate repository path: {entry.path}",
                )
            seen.add(relative)
            target = destination / relative
            if entry.is_dir:
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                files.append((entry, target))

        for offset in range(0, len(files), 500):
            batch = files[offset : offset + 500]
            requests = [
                DaytonaDownloadRequest(entry.path, str(target))
                for entry, target in batch
            ]
            responses = await self.api.download_files(
                self._sandbox_id(branch),
                requests,
                timeout_s=self.file_timeout_s,
            )
            expected = {entry.path: (entry, target) for entry, target in batch}
            completed: set[str] = set()
            for response in responses:
                item = expected.get(response.source)
                if item is None or response.source in completed:
                    raise OSError(f"Daytona returned an unexpected download: {response.source}")
                completed.add(response.source)
                entry, target = item
                if response.error is not None:
                    raise OSError(
                        f"Daytona could not download {response.source}: {response.error}",
                    )
                if isinstance(response.result, bytes):
                    target.write_bytes(response.result)
                if not target.is_file() or target.is_symlink():
                    raise OSError(f"Daytona did not download a regular file: {response.source}")
                try:
                    remote_mode = int(entry.permissions, 8)
                except ValueError as exc:
                    raise OSError(
                        f"Daytona returned invalid permissions for {entry.path}: {entry.permissions}",
                    ) from exc
                local_mode = stat.S_IMODE(target.stat().st_mode)
                target.chmod((local_mode & ~0o111) | (remote_mode & 0o111))
            missing = set(expected) - completed
            if missing:
                rendered = ", ".join(sorted(missing))
                raise OSError(f"Daytona omitted downloads: {rendered}")
        return time.monotonic() - started

    async def _trusted_git(self, root: Path, *args: str) -> bytes:
        command = git_command(self._git, *args)
        stdout, stderr, code, timed_out, _, _ = await self._execute_host(
            root,
            command,
            120,
            env_overrides=git_environment(self.root),
        )
        if timed_out or code != 0:
            detail = _tail(stderr) or _tail(stdout) or "no output"
            raise OSError(f"trusted git command failed: {detail}")
        return stdout

    async def _restore_checkpoint_symlinks(self, checkpoint_tree: Path) -> tuple[Path, ...]:
        if not os.path.lexists(checkpoint_tree / ".git"):
            return ()
        index = await self._trusted_git(checkpoint_tree, "ls-files", "-s", "-z")
        symlink_paths: list[Path] = []
        seen: set[Path] = set()
        for record in index.split(b"\0"):
            if not record:
                continue
            metadata, separator, path_bytes = record.partition(b"\t")
            fields = metadata.split()
            if not separator or not path_bytes or len(fields) != 3:
                raise OSError("trusted git returned a malformed index entry")
            mode, object_id, stage = fields
            if mode != b"120000":
                continue
            if stage != b"0" or re.fullmatch(
                rb"(?:[0-9a-f]{40}|[0-9a-f]{64})",
                object_id,
            ) is None:
                raise OSError("trusted git returned an invalid symlink index entry")
            relative = Path(os.fsdecode(path_bytes))
            if relative.is_absolute() or any(
                part in ("", ".", "..") for part in relative.parts
            ):
                raise OSError("trusted git returned an invalid symlink path")
            if relative in seen:
                raise OSError("trusted git returned a duplicate symlink path")
            seen.add(relative)
            target_bytes = await self._trusted_git(
                checkpoint_tree,
                "cat-file",
                "blob",
                object_id.decode("ascii"),
            )
            if not target_bytes or b"\0" in target_bytes:
                raise OSError(
                    f"trusted git returned an invalid symlink target: {relative.as_posix()}",
                )
            await asyncio.to_thread(
                _set_symlink,
                checkpoint_tree / relative,
                os.fsdecode(target_bytes),
            )
            symlink_paths.append(relative)
        return tuple(symlink_paths)

    async def _tree_digest_with_download_time(
        self,
        branch: Branch,
    ) -> tuple[str, float]:
        destination = self.root / "staging" / f"digest-{branch.id}-{uuid.uuid4().hex[:12]}"
        try:
            download_s = await self._download_tree(
                branch,
                destination,
                skip=_tree_digest_ignores,
            )
            digest = await asyncio.to_thread(_tree_digest, destination)
            return digest, download_s
        finally:
            if destination.exists():
                await asyncio.to_thread(remove_path, destination)

    async def _tree_digest(self, branch: Branch) -> str:
        digest, _ = await self._tree_digest_with_download_time(branch)
        return digest

    async def _execute_host(
        self,
        workdir: Path,
        command: str,
        timeout_s: int,
        *,
        env_overrides: dict[str, str] | None = None,
    ) -> tuple[bytes, bytes, int | None, bool, datetime, float]:
        env = {
            "PATH": os.defpath,
            "HOME": str(self.root),
            "LANG": "C.UTF-8",
        }
        if env_overrides:
            env.update(env_overrides)
        started = _now()
        process = await asyncio.create_subprocess_exec(
            str(self._bash),
            "-c",
            command,
            cwd=workdir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
            exit_code: int | None = process.returncode
        except asyncio.TimeoutError:
            timed_out = True
            exit_code = None
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = await process.communicate()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return (
            stdout,
            stderr,
            exit_code,
            timed_out,
            started,
            (_now() - started).total_seconds(),
        )

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
        self._record_sandbox_created(sandbox.id)
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

    async def run_pytest(
        self,
        branch: Branch,
        args: str,
        timeout_s: int,
        kind: ReceiptKind = "command",
    ) -> Receipt:
        seq = self._seq.get(branch.id, 0) + 1
        spec = self._spec(branch)
        remote_report = f"/opt/receipts/reports/{branch.id}-{seq}.xml"
        local_report = self.root / "reports" / f"{branch.id}-{seq}.xml"
        local_report.unlink(missing_ok=True)
        command = (
            f"{shlex.quote(spec.python)} -I /opt/receipts/receipts_pytest.py "
            f"{args} {PYTEST_FLAGS} --junitxml={shlex.quote(remote_report)}"
        )
        output, code, timed_out, started, duration = await self._execute(
            branch,
            command,
            timeout_s,
            env={"PYTEST_ADDOPTS": "", "PYTEST_PLUGINS": ""},
        )
        report = await self.api.download_file(
            self._sandbox_id(branch),
            remote_report,
            timeout_s=self.file_timeout_s,
        )
        if report is not None:
            local_report.write_bytes(report)
        junit = parse_junit(local_report if local_report.exists() else None)
        log_path = self._write_log(branch, output)
        tree_digest, tree_download_s = await self._tree_digest_with_download_time(branch)
        return self._emit(
            branch,
            kind=kind,
            cmd=command,
            exit_code=code,
            stdout_tail=_tail(output),
            stderr_tail="",
            stdout_sha256=hashlib.sha256(output).hexdigest(),
            log_path=str(log_path),
            started_at=started,
            duration_s=duration,
            timed_out=timed_out,
            junit=junit,
            tree_digest=tree_digest,
            tree_download_s=tree_download_s,
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
        checkpoint_tree = self.root / "checkpoints" / hashlib.sha256(
            snapshot.ref.encode(),
        ).hexdigest()
        await self._download_tree(branch, checkpoint_tree, skip=_skip_nothing)
        symlink_paths = await self._restore_checkpoint_symlinks(checkpoint_tree)
        self._checkpoint_trees[snapshot.ref] = checkpoint_tree
        self._checkpoint_symlinks[snapshot.ref] = symlink_paths
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
            self._record_sandbox_created(sandbox.id)
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

    async def patch(self, branch: Branch, snapshot_sha: str) -> Receipt:
        started = _now()
        checkpoint_tree = self._checkpoint_trees.get(branch.origin)
        checkpoint_symlinks = self._checkpoint_symlinks.get(branch.origin)
        if checkpoint_tree is None or checkpoint_symlinks is None:
            message = f"trusted checkpoint tree is unavailable: {branch.origin}".encode()
            return self._emit(
                branch,
                kind="diff",
                cmd="compute patch in executor staging",
                exit_code=1,
                stderr_tail=_tail(message),
                stdout_sha256=hashlib.sha256(b"").hexdigest(),
                started_at=started,
                duration_s=(_now() - started).total_seconds(),
            )

        token = uuid.uuid4().hex[:12]
        staging = self.root / "staging" / f"{branch.id}-{token}"
        agent_tree = self.root / "staging" / f"{branch.id}-{token}-agent"
        try:
            await asyncio.to_thread(
                shutil.copytree,
                checkpoint_tree,
                staging,
                symlinks=True,
            )
            tree_download_s = await self._download_tree(
                branch,
                agent_tree,
                skip=_skip_top_level_git,
            )
            # Hash the tree as downloaded, the same view every test-run receipt
            # hashes, so the claim audit can compare the two; symlinks are put
            # back only for the patch itself.
            tree_digest = await asyncio.to_thread(_tree_digest, agent_tree)
            await asyncio.to_thread(
                _copy_checkpoint_symlinks,
                checkpoint_tree,
                agent_tree,
                checkpoint_symlinks,
            )
            await asyncio.to_thread(mirror_worktree, agent_tree, staging)
        except (OSError, shutil.Error) as exc:
            for path in (agent_tree, staging):
                if path.exists():
                    await asyncio.to_thread(remove_path, path)
            message = f"trusted patch staging failed: {exc}".encode()
            return self._emit(
                branch,
                kind="diff",
                cmd="compute patch in executor staging",
                exit_code=1,
                stderr_tail=_tail(message),
                stdout_sha256=hashlib.sha256(b"").hexdigest(),
                started_at=started,
                duration_s=(_now() - started).total_seconds(),
            )

        command = patch_command(self._git, snapshot_sha)
        display_command = f"compute patch in executor staging {staging.name}: {command}"
        try:
            stdout, stderr, code, timed_out, command_started, duration = (
                await self._execute_host(
                    staging,
                    command,
                    120,
                    env_overrides=git_environment(self.root),
                )
            )
        finally:
            for path in (agent_tree, staging):
                if path.exists():
                    await asyncio.to_thread(remove_path, path)
        if code != 0:
            return self._emit(
                branch,
                kind="diff",
                cmd=display_command,
                exit_code=1,
                stdout_tail=_tail(stdout),
                stderr_tail=_tail(stderr),
                stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                started_at=command_started,
                duration_s=duration,
                timed_out=timed_out,
                tree_digest=tree_digest,
                tree_download_s=tree_download_s,
            )

        patch_text = stdout.decode(errors="replace")
        seq = self._seq.get(branch.id, 0) + 1
        patch_path = self.root / "patches" / f"{branch.id}-{seq}-full.diff"
        patch_path.write_text(patch_text)
        summary = summarize_patch(patch_text, self._protected_modules).model_copy(
            update={"patch_path": str(patch_path)},
        )
        _, dropped = filter_patch(patch_text, self._protected_modules)
        return self._emit(
            branch,
            kind="diff",
            cmd=display_command,
            exit_code=0,
            stdout_tail=patch_text[-TAIL:],
            stderr_tail=_tail(stderr),
            stdout_sha256=summary.patch_sha256,
            started_at=command_started,
            duration_s=duration,
            timed_out=timed_out,
            tree_digest=tree_digest,
            tree_download_s=tree_download_s,
            diff=summary,
            dropped_paths=dropped,
        )

    async def apply_patch(self, branch: Branch, patch_text: str) -> Receipt:
        started = _now()
        digest = hashlib.sha256(patch_text.encode()).hexdigest()
        seq = self._seq.get(branch.id, 0) + 1
        local_patch = self.root / "patches" / f"{branch.id}-{seq}-apply.diff"
        local_patch.write_text(patch_text)
        remote_patch = f"/opt/receipts/{branch.id}-{seq}-apply.diff"
        await self.api.upload_file(
            self._sandbox_id(branch),
            patch_text.encode(),
            remote_patch,
            timeout_s=self.file_timeout_s,
        )
        command = (
            "git update-index -q --refresh; "
            f"git apply {GIT_APPLY_FLAGS} {shlex.quote(remote_patch)}"
        )
        if patch_text:
            output, code, timed_out, command_started, duration = await self._execute(
                branch,
                command,
                120,
            )
        else:
            output = b""
            code = 0
            timed_out = False
            command_started = started
            duration = (_now() - started).total_seconds()
        tree_digest, tree_download_s = await self._tree_digest_with_download_time(branch)
        return self._emit(
            branch,
            kind="apply",
            cmd=command,
            exit_code=code,
            stdout_tail=_tail(output),
            stderr_tail="",
            stdout_sha256=hashlib.sha256(output).hexdigest(),
            patch_sha256=digest,
            started_at=command_started,
            duration_s=duration,
            timed_out=timed_out,
            tree_digest=tree_digest,
            tree_download_s=tree_download_s,
        )

    async def release(self, branch: Branch) -> None:
        if branch.id in self._released_branches:
            return
        sandbox_id = self._sandbox_id(branch)
        try:
            await self.api.delete_sandbox(sandbox_id, timeout_s=120)
        except Exception as exc:
            if self._status_code(exc) != 404:
                raise
        self._record_sandbox_deleted(sandbox_id)
        self._created_sandboxes = [
            created_id
            for created_id in self._created_sandboxes
            if created_id != sandbox_id
        ]
        self._sandboxes.pop(branch.id, None)
        self._specs.pop(branch.id, None)
        self._roots.pop(branch.id, None)
        self._released_branches.add(branch.id)

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
            if sandbox_id in deleted:
                return
            try:
                await self.api.delete_sandbox(sandbox_id, timeout_s=120)
            except Exception as exc:  # Cleanup must continue after one provider failure.
                if self._status_code(exc) != 404:
                    failures[f"sandbox {sandbox_id}"] = str(exc)
                    return
            self._record_sandbox_deleted(sandbox_id)
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
