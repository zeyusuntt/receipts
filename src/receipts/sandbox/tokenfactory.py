"""Token Factory Sandboxes executor backed by immutable image chains."""

from __future__ import annotations

import hashlib
import json
import posixpath
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from receipts.models import Branch, Checkpoint, Receipt, ReceiptKind
from receipts.sandbox.protocol import PYTEST_BOOTSTRAP, ImageSource, Source
from receipts.sandbox.sink import ReceiptSink
from receipts.sandbox.tokenfactory_api import (
    InstanceFileSpec,
    RunResult,
    TokenFactoryApiError,
    UploadedFile,
)


TAIL = 6_000
_SCRATCH_ROOT = "/tmp"
_BUSYBOX_PATH = "/opt/receipts-bin/busybox"
_PYTEST_PATH = "/opt/receipts/receipts_pytest.py"
_INCOMING_ROOT = "/opt/receipts/incoming"
_SNAPSHOT_COMMAND = (
    "git add -A && git -c user.name=receipts "
    "-c user.email=receipts@localhost commit -q --allow-empty "
    '-m "receipts snapshot" && git rev-parse HEAD'
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tail(text: str) -> str:
    return text[-TAIL:]


@dataclass(frozen=True)
class _BranchSpec:
    workdir: str
    python: str


@dataclass(frozen=True)
class _Execution:
    before: str
    after: str
    result: RunResult
    started_at: datetime
    finished_at: datetime


class TokenFactoryExecutor:
    def __init__(
        self,
        root: Path,
        sink: ReceiptSink,
        run_id: str,
        api: Any,
        *,
        busybox: bytes,
        truncate_output_at: int = 64 * 1024 * 1024,
        run_timeout_cap_s: int = 3600,
        hostname: str = "receipts",
    ) -> None:
        if not isinstance(busybox, bytes):
            raise TypeError("busybox must be bytes")
        if not busybox:
            raise ValueError("busybox must not be empty")
        if truncate_output_at <= 0:
            raise ValueError("truncate_output_at must be positive")
        if run_timeout_cap_s <= 0:
            raise ValueError("run_timeout_cap_s must be positive")
        if not hostname:
            raise ValueError("hostname must not be empty")

        self.root = Path(root)
        self.sink = sink
        self.run_id = run_id
        self.api = api
        self.truncate_output_at = truncate_output_at
        self.run_timeout_cap_s = run_timeout_cap_s
        self.hostname = hostname
        self.cleanup_manifest: Path | None = None

        self._busybox = bytes(busybox)
        self._busybox_upload: UploadedFile | None = None
        self._pytest_upload: UploadedFile | None = None
        self._seq: dict[str, int] = {}
        self._heads: dict[str, str] = {}
        self._specs: dict[str, _BranchSpec] = {}
        self._checkpoint_specs: dict[str, _BranchSpec] = {}
        self._fork_next: dict[str, int] = {}
        self._released_branches: set[str] = set()
        self._usage: list[dict[str, Any]] = []
        self._prepared = False
        self._closed = False

        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(exist_ok=True)

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

    def _trusted_files(self) -> dict[str, InstanceFileSpec]:
        if self._busybox_upload is None or self._pytest_upload is None:
            raise RuntimeError("trusted Token Factory files have not been uploaded")
        return {
            _BUSYBOX_PATH: InstanceFileSpec(
                uuid=self._busybox_upload.uuid,
                mode="0755",
                uid=0,
                gid=0,
            ),
            _PYTEST_PATH: InstanceFileSpec(
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
        extra_files: dict[str, InstanceFileSpec] | None = None,
    ) -> _Execution:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        await self._ensure_tools()
        before = self._head(branch)
        files = self._trusted_files()
        if extra_files:
            files.update(extra_files)
        started_at = _now()
        result = await self.api.run(
            command=command,
            image=before,
            hostname=self.hostname,
            shell=True,
            cwd=self._spec(branch).workdir,
            disposable=False,
            timeout=min(timeout_s, self.run_timeout_cap_s),
            truncate_output_at=self.truncate_output_at,
            files=files,
        )
        finished_at = _now()
        self._record_usage(branch, result, started_at, finished_at)
        if result.status.upper() != "SUCCESS" and not result.has_process_result:
            detail = result.error or f"status {result.status or 'unknown'}"
            raise RuntimeError(f"Token Factory sandbox operation failed: {detail}")

        after = result.image_uuid or before
        self._heads[branch.id] = after
        branch.head = after
        return _Execution(
            before=before,
            after=after,
            result=result,
            started_at=started_at,
            finished_at=finished_at,
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
    ) -> Receipt:
        result = execution.result
        output = (result.stdout + result.stderr).encode()
        log_path = self._write_log(branch, output)
        return self._emit(
            branch,
            before=execution.before,
            after=execution.after,
            kind=kind,
            cmd=command,
            path=path,
            exit_code=result.exit_code,
            stdout_tail=_tail(result.stdout),
            stderr_tail=_tail(result.stderr),
            stdout_sha256=stdout_sha256 or hashlib.sha256(output).hexdigest(),
            log_path=str(log_path),
            started_at=execution.started_at,
            duration_s=max(0.0, result.duration_s),
            timed_out=result.timed_out,
            snapshot_sha=snapshot_sha,
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
        raise NotImplementedError("TF-3")

    async def read_file(self, branch: Branch, path: str, max_bytes: int) -> str:
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        remote_path = self._file_path(branch, path)
        if remote_path is None:
            return ""
        image = self._head(branch)
        content = await self.api.download(image, remote_path)
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
            candidate = PurePosixPath(posixpath.normpath(str(entry["path"])))
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
        incoming = f"{_INCOMING_ROOT}/{digest}"
        parent = posixpath.dirname(remote_path)
        inner = (
            f"mkdir -p {shlex.quote(parent)} && "
            f"cp {shlex.quote(incoming)} {shlex.quote(remote_path)}"
        )
        command = (
            f"{shlex.quote(_BUSYBOX_PATH)} sh -c {shlex.quote(inner)}"
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
        raise NotImplementedError("TF-3")

    async def apply_patch(self, branch: Branch, patch_text: str) -> Receipt:
        raise NotImplementedError("TF-3")

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
