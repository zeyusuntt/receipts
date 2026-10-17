"""Token Factory Sandboxes executor backed by immutable image chains."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import os
import posixpath
import shlex
import shutil
import signal
import stat
import tarfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from receipts.junit import parse_junit
from receipts.models import Branch, Checkpoint, Receipt, ReceiptKind
from receipts.patchscope import default_protected_modules, filter_patch, summarize_patch
from receipts.sandbox.protocol import (
    GIT_APPLY_FLAGS,
    PYTEST_BOOTSTRAP,
    PYTEST_FLAGS,
    ImageSource,
    Source,
)
from receipts.sandbox.sink import ReceiptSink
from receipts.sandbox.staging import (
    git_environment,
    mirror_worktree,
    patch_command,
    remove_path,
)
from receipts.sandbox.tokenfactory_api import (
    MAX_TRUNCATE_OUTPUT_AT,
    InstanceFileSpec,
    RunResult,
    TokenFactoryApiError,
    UploadedFile,
)
from receipts.sandbox.tree import tree_digest as _tree_digest
from receipts.verify.shortcuts import find_shortcuts


TAIL = 6_000
_SCRATCH_ROOT = "/tmp"
_REPORTS_ROOT = "/opt/receipts/reports"
_DEFAULT_ARCHIVE_SIZE_CAP_BYTES = 512 * 1024 * 1024
_DEFAULT_ARCHIVE_MEMBER_CAP = 200_000
_DEFAULT_ARCHIVE_MEMBER_PATH_CAP_BYTES = 4_096
_DEFAULT_CLIENT_TIMEOUT_ALLOWANCE_S = 600.0
_SNAPSHOT_COMMAND = (
    "git add -A && git -c user.name=receipts "
    "-c user.email=receipts@localhost commit -q --allow-empty "
    '-m "receipts snapshot" && git rev-parse HEAD'
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tail(text: str) -> str:
    return text[-TAIL:]


def _tail_bytes(data: bytes) -> str:
    return data.decode(errors="replace")[-TAIL:]


def _archive_path(name: str, *, description: str) -> PurePosixPath:
    if not name or "\x00" in name:
        raise OSError(f"unsafe Token Factory archive: invalid {description}")
    candidate = PurePosixPath(name)
    if candidate.is_absolute() or name.startswith("/"):
        raise OSError(
            f"unsafe Token Factory archive: absolute {description}: {name}",
        )
    parts: list[str] = []
    for part in candidate.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise OSError(
                f"unsafe Token Factory archive: parent traversal in {description}: {name}",
            )
        parts.append(part)
    return PurePosixPath(*parts) if parts else PurePosixPath(".")


class _ArchiveLimitError(RuntimeError):
    """A bounded archive refusal that must classify as infrastructure."""


def _safe_extract_tar(
    archive_bytes: bytes,
    destination: Path,
    *,
    size_cap_bytes: int = _DEFAULT_ARCHIVE_SIZE_CAP_BYTES,
    member_cap: int = _DEFAULT_ARCHIVE_MEMBER_CAP,
    member_path_cap_bytes: int = _DEFAULT_ARCHIVE_MEMBER_PATH_CAP_BYTES,
) -> None:
    """Extract an agent-controlled tar without following archive symlinks."""

    if size_cap_bytes <= 0:
        raise ValueError("archive size cap must be positive")
    if member_cap <= 0:
        raise ValueError("archive member cap must be positive")
    if member_path_cap_bytes <= 0:
        raise ValueError("archive member path cap must be positive")
    if len(archive_bytes) > size_cap_bytes:
        raise _ArchiveLimitError(
            "Token Factory archive exceeds size cap "
            f"of {size_cap_bytes} bytes: {len(archive_bytes)} bytes",
        )
    if os.path.lexists(destination):
        raise OSError(f"Token Factory archive destination already exists: {destination}")

    try:
        archive = tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*")
    except (tarfile.TarError, OSError) as exc:
        raise OSError(f"unsafe Token Factory archive: invalid tar: {exc}") from exc

    with archive:
        normalized: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
        by_path: dict[PurePosixPath, tarfile.TarInfo] = {}
        symlinks: set[PurePosixPath] = set()
        extracted_size = 0
        allowed = (
            tarfile.DIRTYPE,
            tarfile.REGTYPE,
            tarfile.AREGTYPE,
            tarfile.SYMTYPE,
            tarfile.LNKTYPE,
        )
        for member_count, member in enumerate(archive, start=1):
            if member_count > member_cap:
                raise _ArchiveLimitError(
                    "Token Factory archive exceeds member cap "
                    f"of {member_cap}: {member_count} members",
                )
            path_bytes = len(member.name.encode("utf-8", errors="surrogateescape"))
            if path_bytes > member_path_cap_bytes:
                raise _ArchiveLimitError(
                    "Token Factory archive member path exceeds "
                    f"{member_path_cap_bytes} bytes: {path_bytes} bytes: {member.name}",
                )
            if member.isreg():
                extracted_size += member.size
                if extracted_size > size_cap_bytes:
                    raise _ArchiveLimitError(
                        "Token Factory archive exceeds size cap "
                        f"of {size_cap_bytes} bytes after extraction: "
                        f"{extracted_size} bytes",
                    )
            path = _archive_path(member.name, description="member path")
            if member.type not in allowed:
                raise OSError(
                    "unsafe Token Factory archive: special member refused: "
                    f"{member.name}",
                )
            if path == PurePosixPath(".") and not member.isdir():
                raise OSError("unsafe Token Factory archive: non-directory root member")
            if path in by_path:
                raise OSError(
                    f"unsafe Token Factory archive: duplicate member path: {member.name}",
                )
            by_path[path] = member
            normalized.append((member, path))
            if member.issym():
                symlinks.add(path)

        def parents(path: PurePosixPath) -> tuple[PurePosixPath, ...]:
            return tuple(path.parents[:-1])

        for member, path in normalized:
            crossed = next((parent for parent in parents(path) if parent in symlinks), None)
            if crossed is not None:
                raise OSError(
                    "unsafe Token Factory archive: member path passes through symlink "
                    f"{crossed.as_posix()}: {member.name}",
                )
            if member.islnk():
                target = _archive_path(member.linkname, description="hard-link target")
                crossed_target = next(
                    (parent for parent in (target, *parents(target)) if parent in symlinks),
                    None,
                )
                if crossed_target is not None:
                    raise OSError(
                        "unsafe Token Factory archive: hard-link target passes through "
                        f"symlink {crossed_target.as_posix()}: {member.linkname}",
                    )
                target_member = by_path.get(target)
                if target_member is None or not (target_member.isreg() or target_member.islnk()):
                    raise OSError(
                        "unsafe Token Factory archive: invalid hard-link target: "
                        f"{member.linkname}",
                    )

        destination.mkdir(parents=True)
        directories = sorted(
            ((member, path) for member, path in normalized if member.isdir()),
            key=lambda item: len(item[1].parts),
        )
        for _member, path in directories:
            if path != PurePosixPath("."):
                destination.joinpath(*path.parts).mkdir()

        for member, path in normalized:
            if not member.isreg():
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise OSError(
                    f"unsafe Token Factory archive: missing file data: {member.name}",
                )
            data = source.read(size_cap_bytes + 1)
            if len(data) != member.size:
                raise OSError(
                    f"unsafe Token Factory archive: truncated file data: {member.name}",
                )
            target.write_bytes(data)
            target.chmod(stat.S_IMODE(member.mode), follow_symlinks=False)

        def hard_target(path: PurePosixPath, seen: set[PurePosixPath]) -> PurePosixPath:
            if path in seen:
                raise OSError("unsafe Token Factory archive: hard-link cycle")
            member = by_path[path]
            if member.isreg():
                return path
            target = _archive_path(member.linkname, description="hard-link target")
            return hard_target(target, {*seen, path})

        for member, path in normalized:
            if not member.islnk():
                continue
            source_path = hard_target(
                _archive_path(member.linkname, description="hard-link target"),
                {path},
            )
            source = destination.joinpath(*source_path.parts)
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target, follow_symlinks=False)

        # Symlinks are created last and their literal targets are never resolved.
        # Outside-pointing links must remain links so the patch-scope gate can see them.
        for member, path in normalized:
            if not member.issym():
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(member.linkname)

        for member, path in reversed(directories):
            target = (
                destination
                if path == PurePosixPath(".")
                else destination.joinpath(*path.parts)
            )
            target.chmod(stat.S_IMODE(member.mode), follow_symlinks=False)


@dataclass(frozen=True)
class _BranchSpec:
    workdir: str
    python: str


@dataclass(frozen=True)
class _RunPaths:
    root: str
    busybox: str
    pytest: str

    @classmethod
    def fresh(cls) -> _RunPaths:
        root = f"/opt/receipts-{uuid.uuid4().hex}"
        return cls(
            root=root,
            busybox=f"{root}/bin/busybox",
            pytest=f"{root}/receipts_pytest.py",
        )

    def incoming(self, name: str) -> str:
        return f"{self.root}/incoming/{name}"


@dataclass(frozen=True)
class _Execution:
    before: str
    after: str
    result: RunResult
    started_at: datetime
    finished_at: datetime
    duration_s: float


class TokenFactoryExecutor:
    def __init__(
        self,
        root: Path,
        sink: ReceiptSink,
        run_id: str,
        api: Any,
        *,
        busybox: bytes,
        truncate_output_at: int = MAX_TRUNCATE_OUTPUT_AT,
        run_timeout_cap_s: int = 3600,
        client_timeout_allowance_s: float = _DEFAULT_CLIENT_TIMEOUT_ALLOWANCE_S,
        hostname: str = "receipts",
        archive_size_cap_bytes: int = _DEFAULT_ARCHIVE_SIZE_CAP_BYTES,
        archive_member_cap: int = _DEFAULT_ARCHIVE_MEMBER_CAP,
        archive_member_path_cap_bytes: int = _DEFAULT_ARCHIVE_MEMBER_PATH_CAP_BYTES,
    ) -> None:
        if not isinstance(busybox, bytes):
            raise TypeError("busybox must be bytes")
        if not busybox:
            raise ValueError("busybox must not be empty")
        if not 0 < truncate_output_at <= MAX_TRUNCATE_OUTPUT_AT:
            raise ValueError(
                f"truncate_output_at must be between 1 and {MAX_TRUNCATE_OUTPUT_AT}",
            )
        if run_timeout_cap_s <= 0:
            raise ValueError("run_timeout_cap_s must be positive")
        if not math.isfinite(client_timeout_allowance_s) or client_timeout_allowance_s < 0:
            raise ValueError("client_timeout_allowance_s must be finite and non-negative")
        if not hostname:
            raise ValueError("hostname must not be empty")
        if archive_size_cap_bytes <= 0:
            raise ValueError("archive_size_cap_bytes must be positive")
        if archive_member_cap <= 0:
            raise ValueError("archive_member_cap must be positive")
        if archive_member_path_cap_bytes <= 0:
            raise ValueError("archive_member_path_cap_bytes must be positive")

        self.root = Path(root)
        self.sink = sink
        self.run_id = run_id
        self.api = api
        self.truncate_output_at = truncate_output_at
        self.run_timeout_cap_s = run_timeout_cap_s
        self.client_timeout_allowance_s = client_timeout_allowance_s
        self.hostname = hostname
        self.archive_size_cap_bytes = archive_size_cap_bytes
        self.archive_member_cap = archive_member_cap
        self.archive_member_path_cap_bytes = archive_member_path_cap_bytes
        self.cleanup_manifest: Path | None = None

        self._busybox = bytes(busybox)
        self._busybox_upload: UploadedFile | None = None
        self._pytest_upload: UploadedFile | None = None
        self._seq: dict[str, int] = {}
        self._heads: dict[str, str] = {}
        self._specs: dict[str, _BranchSpec] = {}
        self._checkpoint_specs: dict[str, _BranchSpec] = {}
        self._checkpoint_trees: dict[str, Path] = {}
        self._checkpoint_cache_lock = asyncio.Lock()
        self._fork_next: dict[str, int] = {}
        self._released_branches: set[str] = set()
        self._usage: list[dict[str, Any]] = []
        self._prepared = False
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
        for directory in ("logs", "reports", "patches", "staging", "checkpoints"):
            (self.root / directory).mkdir(exist_ok=True)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(root={self.root!r}, "
            f"run_id={self.run_id!r}, hostname={self.hostname!r})"
        )

    async def __aenter__(self) -> TokenFactoryExecutor:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    @staticmethod
    def _validate_workdir(workdir: str) -> str:
        path = PurePosixPath(workdir)
        if (
            not path.is_absolute()
            or workdir.startswith("//")
            or posixpath.normpath(workdir) != workdir
        ):
            raise ValueError(
                "Token Factory workdir must be a normalized absolute path: "
                f"{workdir}",
            )
        scratch = PurePosixPath(_SCRATCH_ROOT)
        if path == scratch or path in scratch.parents or scratch in path.parents:
            raise ValueError(
                f"Token Factory workdir must not overlap scratch: {workdir}",
            )
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

    @staticmethod
    def _scratch_remote_path(path: str) -> str | None:
        candidate = PurePosixPath(posixpath.normpath(path))
        root = PurePosixPath(_SCRATCH_ROOT)
        if not candidate.is_absolute():
            return None
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            return None
        if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
            return None
        return posixpath.join(_SCRATCH_ROOT, *relative.parts)

    def _spec(self, branch: Branch) -> _BranchSpec:
        if branch.id in self._released_branches:
            raise RuntimeError(f"released Token Factory branch: {branch.id}")
        try:
            return self._specs[branch.id]
        except KeyError as exc:
            raise RuntimeError(f"unknown Token Factory branch: {branch.id}") from exc

    def _head(self, branch: Branch) -> str:
        self._spec(branch)
        try:
            return self._heads[branch.id]
        except KeyError as exc:
            raise RuntimeError(f"unknown Token Factory branch: {branch.id}") from exc

    def _file_path(self, branch: Branch, path: str) -> str | None:
        scratch = self._scratch_remote_path(path)
        if scratch is not None:
            self._spec(branch)
            return scratch
        parts = self._path_parts(path)
        if parts is None:
            return None
        return posixpath.join(self._spec(branch).workdir, *parts)

    async def _ensure_tools(self) -> None:
        if self._busybox_upload is None:
            self._busybox_upload = await self.api.upload(self._busybox)
        if self._pytest_upload is None:
            self._pytest_upload = await self.api.upload(PYTEST_BOOTSTRAP.encode())

    def _trusted_files(self, run_paths: _RunPaths) -> dict[str, InstanceFileSpec]:
        if self._busybox_upload is None or self._pytest_upload is None:
            raise RuntimeError("trusted Token Factory files have not been uploaded")
        return {
            run_paths.busybox: InstanceFileSpec(
                uuid=self._busybox_upload.uuid,
                mode="0755",
                uid=0,
                gid=0,
            ),
            run_paths.pytest: InstanceFileSpec(
                uuid=self._pytest_upload.uuid,
                mode="0644",
                uid=0,
                gid=0,
            ),
        }

    def _record_usage(
        self,
        branch: Branch,
        result: RunResult,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        self._usage.append(
            {
                "operation_id": result.operation_id,
                "branch": branch.id,
                "branch_id": branch.id,
                "created_at": started_at.isoformat(),
                "deleted_at": finished_at.isoformat(),
                "seconds": max(0.0, (finished_at - started_at).total_seconds()),
                "duration_s": max(0.0, result.duration_s),
                "cost": max(0.0, result.cost),
                # The current pilot estimator expects Daytona resource keys. Token
                # Factory already reports cost directly, so these zero values keep
                # that compatibility path neutral until its price table changes.
                "resources": {"cpu": 0, "memory": 0, "disk": 0},
            },
        )

    async def _execute(
        self,
        branch: Branch,
        command: str,
        timeout_s: int,
        *,
        env: dict[str, str] | None = None,
        extra_files: dict[str, InstanceFileSpec] | None = None,
        image: str | None = None,
        advance_head: bool = True,
        require_image: bool = False,
        run_paths: _RunPaths | None = None,
    ) -> _Execution:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        await self._ensure_tools()
        before = image or self._head(branch)
        paths = run_paths or _RunPaths.fresh()
        files = self._trusted_files(paths)
        if extra_files:
            files.update(extra_files)
        command_timeout_s = min(timeout_s, self.run_timeout_cap_s)
        started_at = _now()
        monotonic_started = time.monotonic()
        try:
            result = await self.api.run(
                command=command,
                image=before,
                hostname=self.hostname,
                shell=True,
                env=env,
                cwd=self._spec(branch).workdir,
                disposable=False,
                timeout=command_timeout_s,
                truncate_output_at=self.truncate_output_at,
                files=files,
                client_timeout_s=command_timeout_s + self.client_timeout_allowance_s,
            )
        except TimeoutError as exc:
            raise RuntimeError(f"Token Factory run timed out: {exc}") from exc
        duration_s = time.monotonic() - monotonic_started
        finished_at = _now()
        self._record_usage(branch, result, started_at, finished_at)
        if (advance_head or require_image) and result.image_uuid is None:
            raise RuntimeError(
                f"Token Factory run returned no image: {result.operation_id}",
            )
        if result.status.upper() != "SUCCESS" and not result.has_process_result:
            detail = result.error or f"status {result.status or 'unknown'}"
            raise RuntimeError(f"Token Factory sandbox operation failed: {detail}")

        after = result.image_uuid or before
        if advance_head:
            self._heads[branch.id] = after
            branch.head = after
        return _Execution(
            before=before,
            after=after,
            result=result,
            started_at=started_at,
            finished_at=finished_at,
            duration_s=duration_s,
        )

    def _next_seq(self, branch: Branch) -> int:
        return self._seq.get(branch.id, 0) + 1

    def _emit(
        self,
        branch: Branch,
        *,
        before: str,
        after: str,
        **fields: Any,
    ) -> Receipt:
        seq = self._next_seq(branch)
        self._seq[branch.id] = seq
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
        path = self.root / "logs" / f"{branch.id}-{self._next_seq(branch)}.log"
        path.write_bytes(output)
        return path

    def _execution_receipt(
        self,
        branch: Branch,
        execution: _Execution,
        *,
        kind: ReceiptKind,
        command: str,
        path: str | None = None,
        snapshot_sha: str | None = None,
        stdout_sha256: str | None = None,
        junit: Any = None,
        tree_digest: str | None = None,
        tree_download_s: float | None = None,
        patch_sha256: str | None = None,
    ) -> Receipt:
        result = execution.result
        output = (result.stdout + result.stderr).encode()
        stderr_tail = _tail(result.stderr)
        if result.output_truncated:
            # The platform cut the output at truncate_output_at. Writing it as the
            # full log would let official grading parse a partial log, where every
            # missing test counts as failed; with no log, grading fails closed.
            log_path = None
            stderr_tail = _tail(
                "[output truncated by Token Factory Sandboxes; full log unavailable]\n"
                + result.stderr,
            )
        else:
            log_path = str(self._write_log(branch, output))
        return self._emit(
            branch,
            before=execution.before,
            after=execution.after,
            kind=kind,
            cmd=command,
            path=path,
            exit_code=result.exit_code,
            stdout_tail=_tail(result.stdout),
            stderr_tail=stderr_tail,
            stdout_sha256=stdout_sha256 or hashlib.sha256(output).hexdigest(),
            log_path=log_path,
            started_at=execution.started_at,
            duration_s=max(0.0, execution.duration_s),
            timed_out=result.timed_out,
            snapshot_sha=snapshot_sha,
            junit=junit,
            tree_digest=tree_digest,
            tree_download_s=tree_download_s,
            patch_sha256=patch_sha256,
        )

    async def _archive_image(
        self,
        branch: Branch,
        image: str,
        *,
        include_top_level_git: bool,
    ) -> tuple[bytes, float]:
        token = uuid.uuid4().hex
        remote_archive = f"{_SCRATCH_ROOT}/receipts-{token}.tar"
        run_paths = _RunPaths.fresh()
        parts = [
            shlex.quote(run_paths.busybox),
            "tar",
            "-C",
            shlex.quote(self._spec(branch).workdir),
        ]
        if not include_top_level_git:
            parts.append("--exclude=./.git")
        parts.extend(("-cf", shlex.quote(remote_archive), "."))
        command = " ".join(parts)
        started = time.monotonic()
        execution = await self._execute(
            branch,
            command,
            min(300, self.run_timeout_cap_s),
            image=image,
            advance_head=False,
            require_image=True,
            run_paths=run_paths,
        )
        result = execution.result
        if result.timed_out or result.exit_code != 0:
            detail = _tail(result.stderr) or _tail(result.stdout) or "no output"
            raise OSError(f"Token Factory worktree archive failed: {detail}")
        archive = await self.api.download(
            result.image_uuid,
            remote_archive,
            max_bytes=self.archive_size_cap_bytes,
        )
        elapsed = time.monotonic() - started
        if archive is None:
            raise OSError("Token Factory worktree archive was missing from result image")
        if len(archive) > self.archive_size_cap_bytes:
            raise _ArchiveLimitError(
                "Token Factory archive exceeds size cap "
                f"of {self.archive_size_cap_bytes} bytes: {len(archive)} bytes",
            )
        return archive, elapsed

    async def _download_tree_from_image(
        self,
        branch: Branch,
        image: str,
        destination: Path,
        *,
        include_top_level_git: bool,
    ) -> float:
        archive, download_s = await self._archive_image(
            branch,
            image,
            include_top_level_git=include_top_level_git,
        )
        try:
            await asyncio.to_thread(
                _safe_extract_tar,
                archive,
                destination,
                size_cap_bytes=self.archive_size_cap_bytes,
                member_cap=self.archive_member_cap,
                member_path_cap_bytes=self.archive_member_path_cap_bytes,
            )
        except Exception:
            if os.path.lexists(destination):
                await asyncio.to_thread(remove_path, destination)
            raise
        return download_s

    async def _tree_digest_with_download_time(
        self,
        branch: Branch,
    ) -> tuple[str, float]:
        destination = self.root / "staging" / f"digest-{branch.id}-{uuid.uuid4().hex}"
        try:
            download_s = await self._download_tree_from_image(
                branch,
                self._head(branch),
                destination,
                # The digest ignores every .git path, so the top-level history,
                # by far the largest part of a repository, is not archived.
                include_top_level_git=False,
            )
            digest = await asyncio.to_thread(_tree_digest, destination)
            return digest, download_s
        finally:
            if os.path.lexists(destination):
                await asyncio.to_thread(remove_path, destination)

    async def _checkpoint_tree(self, branch: Branch) -> Path:
        checkpoint = branch.origin
        cached = self._checkpoint_trees.get(checkpoint)
        if cached is not None:
            return cached
        async with self._checkpoint_cache_lock:
            cached = self._checkpoint_trees.get(checkpoint)
            if cached is not None:
                return cached
            destination = self.root / "checkpoints" / hashlib.sha256(
                checkpoint.encode(),
            ).hexdigest()
            if os.path.lexists(destination):
                await asyncio.to_thread(remove_path, destination)
            await self._download_tree_from_image(
                branch,
                checkpoint,
                destination,
                include_top_level_git=True,
            )
            self._checkpoint_trees[checkpoint] = destination
            return destination

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
        started_at = _now()
        monotonic_started = time.monotonic()
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
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_s,
            )
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
            started_at,
            time.monotonic() - monotonic_started,
        )

    async def prepare(self, source: Source) -> Branch:
        if self._prepared:
            raise RuntimeError("TokenFactoryExecutor.prepare may only be called once")
        if not isinstance(source, ImageSource):
            raise TypeError("TokenFactoryExecutor requires an ImageSource")
        spec = _BranchSpec(
            workdir=self._validate_workdir(source.workdir),
            python=source.python,
        )
        tag = source.image.removeprefix("docker.io/")
        image_uuid = await self.api.image_by_tag(tag)
        if image_uuid is None:
            raise RuntimeError(
                "image not in the Token Factory Sandboxes catalogue: " + tag,
            )
        self._prepared = True
        branch = Branch(
            id="base",
            run_id=self.run_id,
            head=image_uuid,
            origin=image_uuid,
        )
        self._heads[branch.id] = image_uuid
        self._specs[branch.id] = spec
        await self._ensure_tools()

        for command in source.setup:
            receipt = await self.run(branch, command, timeout_s=1800)
            if receipt.timed_out or receipt.exit_code != 0:
                raise RuntimeError(
                    f"setup command failed (exit {receipt.exit_code}, "
                    f"timed_out={receipt.timed_out}): "
                    f"{(receipt.stdout_tail + receipt.stderr_tail)[-500:]}",
                )
        return branch

    async def run(self, branch: Branch, cmd: str, timeout_s: int) -> Receipt:
        execution = await self._execute(branch, cmd, timeout_s)
        return self._execution_receipt(
            branch,
            execution,
            kind="command",
            command=cmd,
        )

    async def run_pytest(
        self,
        branch: Branch,
        args: str,
        timeout_s: int,
        kind: ReceiptKind = "command",
    ) -> Receipt:
        seq = self._next_seq(branch)
        spec = self._spec(branch)
        run_paths = _RunPaths.fresh()
        remote_report = f"{_REPORTS_ROOT}/{branch.id}-{seq}.xml"
        local_report = self.root / "reports" / f"{branch.id}-{seq}.xml"
        local_report.unlink(missing_ok=True)
        pytest_command = (
            f"{shlex.quote(spec.python)} -I {shlex.quote(run_paths.pytest)} "
            f"{args} {PYTEST_FLAGS} --junitxml={shlex.quote(remote_report)}"
        )
        command = (
            f"{shlex.quote(run_paths.busybox)} mkdir -p "
            f"{shlex.quote(_REPORTS_ROOT)} "
            f"&& {pytest_command}"
        )
        execution = await self._execute(
            branch,
            command,
            timeout_s,
            env={"PYTEST_ADDOPTS": "", "PYTEST_PLUGINS": ""},
            run_paths=run_paths,
        )
        report = await self.api.download(execution.after, remote_report)
        if report is not None:
            local_report.write_bytes(report)
        junit = parse_junit(local_report if local_report.exists() else None)
        tree_digest, tree_download_s = await self._tree_digest_with_download_time(branch)
        return self._execution_receipt(
            branch,
            execution,
            kind=kind,
            command=command,
            junit=junit,
            tree_digest=tree_digest,
            tree_download_s=tree_download_s,
        )

    async def read_file(self, branch: Branch, path: str, max_bytes: int) -> str:
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        remote_path = self._file_path(branch, path)
        if remote_path is None:
            return ""
        image = self._head(branch)
        try:
            content = await self.api.download(image, remote_path)
        except TokenFactoryApiError as exc:
            # The live API refuses to download a directory with 422; list it instead.
            if exc.status_code != 422:
                raise
            content = None
        if content is not None:
            return content[:max_bytes].decode(errors="replace")

        try:
            entries = await self.api.list_files(image, remote_path)
        except TokenFactoryApiError as exc:
            if exc.status_code == 404:
                return ""
            raise
        root = PurePosixPath(posixpath.normpath(remote_path))
        listing: list[str] = []
        for entry in entries:
            # The live API names entries relative to the listed directory.
            listed = str(entry["path"])
            if not listed.startswith("/"):
                listed = posixpath.join(str(root), listed)
            candidate = PurePosixPath(posixpath.normpath(listed))
            try:
                relative = candidate.relative_to(root)
            except ValueError as exc:
                raise OSError(
                    "Token Factory listed a path outside the requested directory: "
                    f"{entry['path']}",
                ) from exc
            if len(relative.parts) != 1:
                continue
            listing.append(relative.parts[0] + ("/" if entry.get("is_dir") else ""))
        rendered = "".join(item + "\n" for item in sorted(listing))
        return rendered.encode()[:max_bytes].decode(errors="replace")

    async def write_file(self, branch: Branch, path: str, content: str) -> Receipt:
        started_at = _now()
        remote_path = self._file_path(branch, path)
        if remote_path is None:
            head = self._head(branch)
            return self._emit(
                branch,
                before=head,
                after=head,
                kind="write",
                path=path,
                exit_code=1,
                stderr_tail="refused: path is outside the repository",
                started_at=started_at,
                duration_s=(_now() - started_at).total_seconds(),
            )

        encoded = content.encode()
        digest = hashlib.sha256(encoded).hexdigest()
        uploaded = await self.api.upload(encoded)
        run_paths = _RunPaths.fresh()
        incoming = run_paths.incoming(digest)
        parent = posixpath.dirname(remote_path)
        inner = (
            f"mkdir -p {shlex.quote(parent)} && "
            f"cp {shlex.quote(incoming)} {shlex.quote(remote_path)}"
        )
        command = (
            f"{shlex.quote(run_paths.busybox)} sh -c {shlex.quote(inner)}"
        )
        execution = await self._execute(
            branch,
            command,
            timeout_s=min(120, self.run_timeout_cap_s),
            extra_files={
                incoming: InstanceFileSpec(
                    uuid=uploaded.uuid,
                    mode="0644",
                    uid=0,
                    gid=0,
                ),
            },
            run_paths=run_paths,
        )
        return self._execution_receipt(
            branch,
            execution,
            kind="write",
            command=command,
            path=path,
            stdout_sha256=digest,
        )

    async def snapshot(self, branch: Branch) -> Receipt:
        execution = await self._execute(branch, _SNAPSHOT_COMMAND, 120)
        snapshot_sha = None
        if execution.result.exit_code == 0:
            lines = execution.result.stdout.splitlines()
            snapshot_sha = lines[-1].strip() if lines else None
        return self._execution_receipt(
            branch,
            execution,
            kind="command",
            command=_SNAPSHOT_COMMAND,
            snapshot_sha=snapshot_sha,
        )

    async def checkpoint(self, branch: Branch) -> Checkpoint:
        head = self._head(branch)
        self._checkpoint_specs[head] = self._spec(branch)
        return Checkpoint(id=head, parent=head, digest=head)

    async def fork(
        self,
        checkpoint: Checkpoint,
        n: int,
        prefix: str = "b",
    ) -> list[Branch]:
        if n < 0:
            raise ValueError("n must be non-negative")
        try:
            spec = self._checkpoint_specs[checkpoint.id]
        except KeyError as exc:
            raise RuntimeError(
                f"unknown Token Factory checkpoint: {checkpoint.id}",
            ) from exc

        branches: list[Branch] = []
        first = self._fork_next.get(prefix, 1)
        for index in range(first, first + n):
            branch_id = f"{prefix}{index}"
            branch = Branch(
                id=branch_id,
                run_id=self.run_id,
                head=checkpoint.id,
                origin=checkpoint.id,
            )
            self._heads[branch_id] = checkpoint.id
            self._specs[branch_id] = spec
            branches.append(branch)
        self._fork_next[prefix] = first + n
        return branches

    async def patch(self, branch: Branch, snapshot_sha: str) -> Receipt:
        started = _now()
        head = self._head(branch)
        token = uuid.uuid4().hex
        staging = self.root / "staging" / f"{branch.id}-{token}"
        agent_tree = self.root / "staging" / f"{branch.id}-{token}-agent"
        try:
            checkpoint_tree = await self._checkpoint_tree(branch)
            await asyncio.to_thread(
                shutil.copytree,
                checkpoint_tree,
                staging,
                symlinks=True,
            )
            tree_download_s = await self._download_tree_from_image(
                branch,
                head,
                agent_tree,
                include_top_level_git=False,
            )
            tree_digest = await asyncio.to_thread(_tree_digest, agent_tree)
            # Token Factory tar archives preserve symlinks, including dangling and
            # outside-pointing links, so Daytona's index-based reconstruction is
            # unnecessary here. Staging never follows those links.
            await asyncio.to_thread(mirror_worktree, agent_tree, staging)
        except (OSError, shutil.Error) as exc:
            for path in (agent_tree, staging):
                if os.path.lexists(path):
                    await asyncio.to_thread(remove_path, path)
            message = f"trusted patch staging failed: {exc}"
            return self._emit(
                branch,
                before=head,
                after=head,
                kind="diff",
                cmd="compute patch in executor staging",
                exit_code=1,
                stderr_tail=_tail(message),
                stdout_sha256=hashlib.sha256(b"").hexdigest(),
                started_at=started,
                duration_s=max(0.0, (_now() - started).total_seconds()),
                snapshot_sha=snapshot_sha,
            )

        command = patch_command(self._git, snapshot_sha)
        display_command = f"compute patch in executor staging {staging.name}: {command}"
        shortcuts = None
        try:
            stdout, stderr, code, timed_out, command_started, duration = (
                await self._execute_host(
                    staging,
                    command,
                    120,
                    env_overrides=git_environment(self.root),
                )
            )
            if code == 0:
                try:
                    shortcuts = await asyncio.to_thread(
                        find_shortcuts, stdout.decode(errors="replace"), staging, self._protected_modules,
                    )
                except Exception:
                    pass
        finally:
            for path in (agent_tree, staging):
                if os.path.lexists(path):
                    await asyncio.to_thread(remove_path, path)

        if code != 0:
            return self._emit(
                branch,
                before=head,
                after=head,
                kind="diff",
                cmd=display_command,
                exit_code=1,
                stdout_tail=_tail_bytes(stdout),
                stderr_tail=_tail_bytes(stderr),
                stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                started_at=command_started,
                duration_s=duration,
                timed_out=timed_out,
                tree_digest=tree_digest,
                tree_download_s=tree_download_s,
                snapshot_sha=snapshot_sha,
            )

        patch_text = stdout.decode(errors="replace")
        patch_path = (
            self.root
            / "patches"
            / f"{branch.id}-{self._next_seq(branch)}-full.diff"
        )
        patch_path.write_text(patch_text)
        summary = summarize_patch(patch_text, self._protected_modules).model_copy(
            update={"patch_path": str(patch_path), "shortcuts": shortcuts},
        )
        _, dropped = filter_patch(patch_text, self._protected_modules)
        return self._emit(
            branch,
            before=head,
            after=head,
            kind="diff",
            cmd=display_command,
            exit_code=0,
            stdout_tail=patch_text[-TAIL:],
            stderr_tail=_tail_bytes(stderr),
            stdout_sha256=summary.patch_sha256,
            patch_sha256=summary.patch_sha256,
            started_at=command_started,
            duration_s=duration,
            timed_out=timed_out,
            tree_digest=tree_digest,
            tree_download_s=tree_download_s,
            diff=summary,
            dropped_paths=dropped,
            snapshot_sha=snapshot_sha,
        )

    async def apply_patch(self, branch: Branch, patch_text: str) -> Receipt:
        digest = hashlib.sha256(patch_text.encode()).hexdigest()
        seq = self._next_seq(branch)
        local_patch = self.root / "patches" / f"{branch.id}-{seq}-apply.diff"
        local_patch.write_text(patch_text)
        run_paths = _RunPaths.fresh()
        remote_patch = run_paths.incoming(f"{digest}.diff")
        command = (
            "git update-index -q --refresh; "
            f"git apply {GIT_APPLY_FLAGS} {shlex.quote(remote_patch)}"
        )
        if not patch_text:
            # As on Daytona: an empty patch (screening grades one) applies nothing,
            # so no run happens and the branch stays at its image.
            started = _now()
            head = self._head(branch)
            tree_digest, tree_download_s = await self._tree_digest_with_download_time(branch)
            return self._emit(
                branch,
                before=head,
                after=head,
                kind="apply",
                cmd=command,
                exit_code=0,
                stdout_tail="",
                stderr_tail="",
                stdout_sha256=hashlib.sha256(b"").hexdigest(),
                patch_sha256=digest,
                started_at=started,
                duration_s=(_now() - started).total_seconds(),
                timed_out=False,
                tree_digest=tree_digest,
                tree_download_s=tree_download_s,
            )
        uploaded = await self.api.upload(patch_text.encode())
        execution = await self._execute(
            branch,
            command,
            120,
            extra_files={
                remote_patch: InstanceFileSpec(
                    uuid=uploaded.uuid,
                    mode="0644",
                    uid=0,
                    gid=0,
                ),
            },
            run_paths=run_paths,
        )
        tree_digest, tree_download_s = await self._tree_digest_with_download_time(branch)
        return self._execution_receipt(
            branch,
            execution,
            kind="apply",
            command=command,
            patch_sha256=digest,
            tree_digest=tree_digest,
            tree_download_s=tree_download_s,
        )

    async def release(self, branch: Branch) -> None:
        if branch.id in self._released_branches:
            return
        self._head(branch)
        self._heads.pop(branch.id, None)
        self._specs.pop(branch.id, None)
        self._released_branches.add(branch.id)

    def scratch_path(self, branch: Branch) -> str:
        self._head(branch)
        return _SCRATCH_ROOT

    def _persist_sandbox_usage(self, usage: list[dict[str, Any]]) -> None:
        if self.cleanup_manifest is None:
            return
        cost_path = Path(self.cleanup_manifest).parent / "cost.json"
        if not cost_path.is_file():
            return
        try:
            cost = json.loads(cost_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(cost, dict):
            return
        cost["sandbox_usage"] = usage
        temporary = cost_path.with_suffix(cost_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(cost, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(cost_path)

    def sandbox_usage(self) -> list[dict[str, Any]]:
        usage = [
            {
                **item,
                "resources": dict(item["resources"]),
            }
            for item in self._usage
        ]
        self._persist_sandbox_usage(usage)
        return usage

    def _write_cleanup_manifest(self) -> None:
        if self.cleanup_manifest is None:
            return
        path = Path(self.cleanup_manifest)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text("[]\n", encoding="utf-8")
        temporary.replace(path)

    async def close(self) -> None:
        if self._closed:
            return
        self._write_cleanup_manifest()
        close = getattr(self.api, "aclose", None)
        if close is not None:
            await close()
        self._closed = True
