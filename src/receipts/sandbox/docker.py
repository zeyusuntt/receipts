"""Docker-backed implementation of the executor lifecycle.

Each branch owns one long-running container. Mutating protocol actions commit
that container and record the resulting content-addressed image id. Checkpoints
are committed images, so forks start from an immutable filesystem state.

Tree digests use a Docker workdir archive and compute the canonical manifest on
the host. This costs one workdir transfer per mutating action, but it includes
ignored and untracked files and does not trust Git inside the worker container.
"""

from __future__ import annotations

import asyncio
import time
import hashlib
import io
import json
import os
import posixpath
import re
import shlex
import shutil
import signal
import stat
import tarfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from receipts.junit import parse_junit
from receipts.models import Branch, Checkpoint, Receipt, ReceiptKind
from receipts.patchscope import default_protected_modules, filter_patch, summarize_patch
from receipts.sandbox.protocol import (
    ImageSource,
    PYTEST_BOOTSTRAP,
    GIT_APPLY_FLAGS,
    PYTEST_FLAGS,
    RepoAtCommit,
    Source,
)
from receipts.sandbox.sink import ReceiptSink
from receipts.sandbox.staging import git_environment, mirror_worktree, patch_command, remove_path

TAIL = 6000
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_WORKDIR_ANCHOR = """\
import json
import os
import sys

resolved = os.path.realpath(sys.argv[1])
try:
    descriptor = os.open(
        resolved,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    metadata = os.fstat(descriptor)
except OSError:
    print("receipts: workdir is not a stable directory", file=sys.stderr)
    raise SystemExit(1)
finally:
    if "descriptor" in globals():
        os.close(descriptor)
print(json.dumps([resolved, metadata.st_dev, metadata.st_ino]))
"""
_WRITE_FILE = """\
import os
import stat
import sys

def refuse():
    print("refused: path is outside the repository", file=sys.stderr)
    raise SystemExit(1)

parts = sys.argv[4:]
if not parts or any(part in ("", ".", "..") or "/" in part for part in parts):
    refuse()
directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
descriptors = []
try:
    current = os.open(sys.argv[1], directory_flags)
    descriptors.append(current)
    root_stat = os.fstat(current)
    if (root_stat.st_dev, root_stat.st_ino) != (int(sys.argv[2]), int(sys.argv[3])):
        refuse()
    for part in parts[:-1]:
        try:
            child = os.open(part, directory_flags, dir_fd=current)
        except FileNotFoundError:
            os.mkdir(part, dir_fd=current)
            child = os.open(part, directory_flags, dir_fd=current)
        descriptors.append(child)
        current = child
    file_flags = (
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    output = os.open(parts[-1], file_flags, 0o666, dir_fd=current)
    descriptors.append(output)
    if not stat.S_ISREG(os.fstat(output).st_mode):
        refuse()
    while True:
        chunk = sys.stdin.buffer.read(65536)
        if not chunk:
            break
        remaining = memoryview(chunk)
        while remaining:
            written = os.write(output, remaining)
            remaining = remaining[written:]
except OSError:
    refuse()
finally:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass
"""
_READ_FILE = """\
import os
import stat
import sys

def refuse():
    print("refused: path is outside the repository", file=sys.stderr)
    raise SystemExit(1)

parts = sys.argv[5:]
if not parts or any(part in ("", ".", "..") or "/" in part for part in parts):
    refuse()
directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
descriptors = []
try:
    current = os.open(sys.argv[1], directory_flags)
    descriptors.append(current)
    root_stat = os.fstat(current)
    if (root_stat.st_dev, root_stat.st_ino) != (int(sys.argv[2]), int(sys.argv[3])):
        refuse()
    for part in parts[:-1]:
        current = os.open(part, directory_flags, dir_fd=current)
        descriptors.append(current)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    source = os.open(parts[-1], file_flags, dir_fd=current)
    descriptors.append(source)
    if not stat.S_ISREG(os.fstat(source).st_mode):
        raise SystemExit(0)
    remaining = int(sys.argv[4])
    while remaining:
        chunk = os.read(source, min(65536, remaining))
        if not chunk:
            break
        sys.stdout.buffer.write(chunk)
        remaining -= len(chunk)
except FileNotFoundError:
    raise SystemExit(0)
except OSError:
    refuse()
finally:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tail(data: bytes) -> str:
    return data.decode(errors="replace")[-TAIL:]


def _tree_manifest_digest(entries: list[tuple[str, int, str]]) -> str:
    serialized = json.dumps(sorted(entries), ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _tree_digest_from_archive(archive_bytes: bytes) -> str:
    entries: list[tuple[str, int, str]] = []
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
        for member in archive:
            raw_path = PurePosixPath(member.name)
            parts = tuple(part for part in raw_path.parts if part not in ("", "."))
            if not parts or raw_path.is_absolute() or ".." in parts or ".git" in parts:
                continue
            if member.isdir():
                continue
            if member.issym():
                mode = stat.S_IFLNK | member.mode
                content_digest = hashlib.sha256(os.fsencode(member.linkname)).hexdigest()
            elif member.isfile() or member.islnk():
                mode = stat.S_IFREG | member.mode
                source = archive.extractfile(member)
                if source is None:
                    raise tarfile.ExtractError(f"could not read archive member: {member.name}")
                content_hash = hashlib.sha256()
                while chunk := source.read(1024 * 1024):
                    content_hash.update(chunk)
                content_digest = content_hash.hexdigest()
            else:
                mode = member.mode
                content_digest = hashlib.sha256(b"").hexdigest()
            entries.append((PurePosixPath(*parts).as_posix(), mode, content_digest))
    return _tree_manifest_digest(entries)


@dataclass(frozen=True)
class _ContainerSpec:
    workdir: str
    python: str
    platform: str | None


@dataclass(frozen=True)
class _WorkdirAnchor:
    path: str
    device: int
    inode: int


class DockerExecutor:
    def __init__(
        self,
        root: Path,
        sink: ReceiptSink,
        run_id: str,
        base_image: str = "receipts-test-base:py312",
        platform: str | None = None,
    ) -> None:
        self.root = root
        self.sink = sink
        self.run_id = run_id
        self.base_image = base_image
        self.platform = platform
        self._seq: dict[str, int] = {}
        self._containers: dict[str, str] = {}
        self._specs: dict[str, _ContainerSpec] = {}
        self._anchors: dict[str, _WorkdirAnchor] = {}
        self._checkpoint_specs: dict[str, _ContainerSpec] = {}
        self._checkpoint_anchors: dict[str, _WorkdirAnchor] = {}
        self._checkpoint_trees: dict[str, Path] = {}
        self._checkpoint_tree_locks: dict[str, asyncio.Lock] = {}
        self._fork_next: dict[str, int] = {}
        self._released_branches: set[str] = set()
        self._created_containers: list[str] = []
        self._owner = uuid.uuid4().hex
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
        tools = self.root / "tools"
        tools.mkdir(exist_ok=True)
        self._pytest_runner = tools / "receipts_pytest.py"
        self._pytest_runner.write_text(PYTEST_BOOTSTRAP)

    async def __aenter__(self) -> DockerExecutor:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

    async def _docker(
        self,
        *args: str,
        input_data: bytes | None = None,
        timeout_s: float = 120,
    ) -> tuple[bytes, bytes, int | None, bool, datetime, float]:
        started = _now()
        started_monotonic = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdin=asyncio.subprocess.PIPE if input_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        host_timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input_data),
                timeout=timeout_s,
            )
            code: int | None = proc.returncode
        except asyncio.TimeoutError:
            host_timed_out = True
            code = None
            proc.kill()
            stdout, stderr = await proc.communicate()
        duration = time.monotonic() - started_monotonic
        return stdout, stderr, code, host_timed_out, started, duration

    async def _checked_docker(
        self,
        *args: str,
        input_data: bytes | None = None,
        timeout_s: float = 120,
        operation: str,
    ) -> bytes:
        stdout, stderr, code, timed_out, _, _ = await self._docker(
            *args,
            input_data=input_data,
            timeout_s=timeout_s,
        )
        if timed_out or code != 0:
            detail = _tail(stderr) or _tail(stdout)
            raise RuntimeError(
                f"{operation} failed (exit {code}, timed_out={timed_out}): {detail}",
            )
        return stdout

    async def _execute_host(
        self,
        workdir: Path,
        cmd: str,
        timeout_s: int,
        env_overrides: dict[str, str] | None = None,
    ) -> tuple[bytes, bytes, int | None, bool, datetime, float]:
        env = {
            "HOME": str(self.root),
            "LANG": "C.UTF-8",
            "PATH": os.defpath,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if env_overrides:
            env.update(env_overrides)
        started = _now()
        proc = await asyncio.create_subprocess_exec(
            str(self._bash),
            "-c",
            cmd,
            cwd=workdir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            code: int | None = proc.returncode
        except asyncio.TimeoutError:
            timed_out = True
            code = None
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = await proc.communicate()
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return stdout, stderr, code, timed_out, started, (_now() - started).total_seconds()

    @staticmethod
    def _validate_workdir(workdir: str) -> str:
        path = PurePosixPath(workdir)
        if not path.is_absolute() or posixpath.normpath(workdir) != workdir:
            raise ValueError(f"container workdir must be a normalized absolute path: {workdir}")
        return workdir

    async def _image_id(self, image: str) -> str:
        stdout = await self._checked_docker(
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            image,
            operation="docker image inspect",
        )
        image_id = stdout.decode(errors="replace").strip()
        if not _IMAGE_ID.fullmatch(image_id):
            raise RuntimeError(f"docker returned a non-content-addressed image id: {image_id}")
        return image_id

    async def _commit(self, container: str) -> str:
        stdout = await self._checked_docker(
            "commit",
            container,
            operation="docker commit",
        )
        image_id = stdout.decode(errors="replace").strip()
        if not _IMAGE_ID.fullmatch(image_id):
            image_id = await self._image_id(image_id)
        return image_id

    async def _reject_image_volumes(self, image: str) -> None:
        stdout = await self._checked_docker(
            "image",
            "inspect",
            "--format",
            "{{json .Config.Volumes}}",
            image,
            operation="inspect image volumes",
        )
        try:
            volumes = json.loads(stdout.decode(errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("docker returned malformed image volume metadata") from exc
        if volumes:
            paths = ", ".join(sorted(volumes))
            raise ValueError(
                f"Docker source image declares volume paths that docker commit would omit: {paths}",
            )

    async def _is_owned_container(self, name: str) -> bool:
        stdout, _, code, timed_out, _, _ = await self._docker(
            "inspect",
            "--format",
            '{{index .Config.Labels "receipts.executor"}}',
            name,
            timeout_s=30,
        )
        return not timed_out and code == 0 and stdout.decode(errors="replace").strip() == self._owner

    async def _start_container(self, image: str, name: str, spec: _ContainerSpec) -> None:
        args = [
            "run",
            "-d",
            "--pull=never",
            "--name",
            name,
            "--label",
            f"receipts.executor={self._owner}",
            "--workdir",
            spec.workdir,
            "--entrypoint",
            "tail",
        ]
        if spec.platform is not None:
            args.extend(["--platform", spec.platform])
        args.extend([image, "-f", "/dev/null"])
        try:
            await self._checked_docker(*args, operation=f"start container {name}")
        except Exception:
            if await self._is_owned_container(name):
                self._created_containers.append(name)
            raise
        self._created_containers.append(name)

    async def _remove_created_container(self, container: str) -> None:
        _, stderr, code, timed_out, _, _ = await self._docker(
            "rm",
            "-f",
            container,
            timeout_s=60,
        )
        message = stderr.decode(errors="replace")
        if (timed_out or code != 0) and "No such container" not in message:
            raise RuntimeError(
                f"failed to remove Docker container {container} "
                f"(exit {code}, timed_out={timed_out}): {message.strip()}",
            )
        try:
            self._created_containers.remove(container)
        except ValueError:
            pass

    def _container(self, branch: Branch) -> str:
        if branch.id in self._released_branches:
            raise RuntimeError(f"released Docker branch: {branch.id}")
        try:
            return self._containers[branch.id]
        except KeyError as exc:
            raise RuntimeError(f"unknown Docker branch: {branch.id}") from exc

    def _spec(self, branch: Branch) -> _ContainerSpec:
        if branch.id in self._released_branches:
            raise RuntimeError(f"released Docker branch: {branch.id}")
        try:
            return self._specs[branch.id]
        except KeyError as exc:
            raise RuntimeError(f"unknown Docker branch: {branch.id}") from exc

    def _anchor(self, branch: Branch) -> _WorkdirAnchor:
        if branch.id in self._released_branches:
            raise RuntimeError(f"released Docker branch: {branch.id}")
        try:
            return self._anchors[branch.id]
        except KeyError as exc:
            raise RuntimeError(f"Docker branch has no workdir anchor: {branch.id}") from exc

    def _emit(self, branch: Branch, image_after: str, **fields) -> Receipt:
        seq = self._seq.get(branch.id, 0) + 1
        self._seq[branch.id] = seq
        image_before = branch.head
        branch.head = image_after
        receipt = Receipt(
            receipt_id=f"{branch.id}-{seq}",
            seq=seq,
            branch_id=branch.id,
            image_before=image_before,
            image_after=image_after,
            **fields,
        )
        self.sink.write(receipt)
        return receipt

    def _write_log(self, branch: Branch, stdout: bytes) -> Path:
        seq = self._seq.get(branch.id, 0) + 1
        log_path = self.root / "logs" / f"{branch.id}-{seq}.log"
        log_path.write_bytes(stdout)
        return log_path

    async def _copy_bootstrap(self, container: str) -> None:
        await self._checked_docker(
            "exec",
            container,
            "mkdir",
            "-p",
            "/opt/receipts",
            "/opt/receipts/reports",
            operation="create trusted runner directory",
        )
        await self._checked_docker(
            "cp",
            str(self._pytest_runner),
            f"{container}:/opt/receipts/receipts_pytest.py",
            operation="copy trusted pytest runner",
        )

    async def _capture_anchor(self, container: str, spec: _ContainerSpec) -> _WorkdirAnchor:
        stdout = await self._checked_docker(
            "exec",
            container,
            spec.python,
            "-I",
            "-c",
            _WORKDIR_ANCHOR,
            spec.workdir,
            operation="capture container workdir anchor",
        )
        try:
            path, device, inode = json.loads(stdout.decode(errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError("container returned malformed workdir metadata") from exc
        if not isinstance(path, str) or not isinstance(device, int) or not isinstance(inode, int):
            raise RuntimeError("container returned malformed workdir metadata")
        return _WorkdirAnchor(path=path, device=device, inode=inode)

    async def _workdir_archive(self, container: str, spec: _ContainerSpec) -> bytes:
        return await self._checked_docker(
            "cp",
            f"{container}:{spec.workdir}/.",
            "-",
            timeout_s=300,
            operation="copy container workdir",
        )

    async def _tree_digest(self, branch: Branch) -> str:
        archive_bytes = await self._workdir_archive(
            self._container(branch),
            self._spec(branch),
        )
        return await asyncio.to_thread(_tree_digest_from_archive, archive_bytes)

    @staticmethod
    def _extract_archive(archive_bytes: bytes, destination: Path) -> None:
        destination.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
            archive.extractall(destination, filter="data")

    async def _checkpoint_tree(self, checkpoint_id: str) -> Path:
        cached = self._checkpoint_trees.get(checkpoint_id)
        if cached is not None:
            return cached
        lock = self._checkpoint_tree_locks.setdefault(checkpoint_id, asyncio.Lock())
        async with lock:
            cached = self._checkpoint_trees.get(checkpoint_id)
            if cached is not None:
                return cached
            try:
                spec = self._checkpoint_specs[checkpoint_id]
            except KeyError as exc:
                raise RuntimeError(f"unknown Docker checkpoint: {checkpoint_id}") from exc
            container = f"{self.run_id}-patch-{uuid.uuid4().hex[:12]}"
            await self._start_container(checkpoint_id, container, spec)
            try:
                archive_bytes = await self._workdir_archive(container, spec)
            finally:
                await self._remove_created_container(container)
            destination = self.root / "checkpoints" / checkpoint_id.removeprefix("sha256:")
            if destination.exists():
                await asyncio.to_thread(remove_path, destination)
            await asyncio.to_thread(self._extract_archive, archive_bytes, destination)
            self._checkpoint_trees[checkpoint_id] = destination
            return destination

    async def _kill_surviving_processes(self, container: str) -> None:
        await self._checked_docker(
            "exec",
            container,
            "sh",
            "-c",
            "kill -9 -1 2>/dev/null || true",
            timeout_s=30,
            operation="terminate surviving container processes",
        )

    async def _restart_container(self, container: str) -> None:
        await self._checked_docker(
            "restart",
            container,
            timeout_s=60,
            operation="restart container after host timeout",
        )

    async def _execute(
        self,
        branch: Branch,
        cmd: str,
        timeout_s: int,
        env_overrides: dict[str, str] | None = None,
    ) -> tuple[bytes, bytes, int | None, bool, datetime, float]:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        spec = self._spec(branch)
        docker_args = [
            "exec",
            "--workdir",
            spec.workdir,
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "LANG=C.UTF-8",
        ]
        for name, value in (env_overrides or {}).items():
            docker_args.extend(["--env", f"{name}={value}"])
        docker_args.extend([
            self._container(branch),
            "timeout",
            "-s",
            "KILL",
            f"{timeout_s}s",
            "sh",
            "-c",
            cmd,
        ])
        stdout, stderr, code, host_timed_out, started, duration = await self._docker(
            *docker_args,
            timeout_s=timeout_s + 5,
        )
        container = self._container(branch)
        if host_timed_out:
            await self._restart_container(container)
        else:
            try:
                await self._kill_surviving_processes(container)
            except RuntimeError:
                await self._restart_container(container)
        internal_timed_out = (
            code in (124, 137)
            and duration >= max(0.5, timeout_s - 0.25)
        )
        timed_out = host_timed_out or internal_timed_out
        return stdout, stderr, None if timed_out else code, timed_out, started, duration

    @staticmethod
    def _path_parts(path: str) -> tuple[str, ...] | None:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            return None
        normalized = posixpath.normpath(path)
        if normalized in ("", ".") or normalized.startswith("../"):
            return None
        return PurePosixPath(normalized).parts

    async def prepare(self, source: Source) -> Branch:
        if "base" in self._containers:
            raise RuntimeError("DockerExecutor.prepare may only be called once")
        if isinstance(source, ImageSource):
            image = source.image
            spec = _ContainerSpec(
                workdir=self._validate_workdir(source.workdir),
                python=source.python,
                platform=source.platform if source.platform is not None else self.platform,
            )
            setup = list(source.setup)
            install_error = "setup command failed"
        elif isinstance(source, RepoAtCommit):
            image = self.base_image
            spec = _ContainerSpec(
                workdir="/workspace",
                python="python",
                platform=self.platform,
            )
            setup = []
            install_error = "install command failed"
        else:
            raise TypeError(f"unsupported source: {type(source).__name__}")

        source_image = await self._image_id(image)
        await self._reject_image_volumes(image)
        container = f"{self.run_id}-base"
        await self._start_container(image, container, spec)
        await self._copy_bootstrap(container)
        bootstrap_image = await self._commit(container)
        branch = Branch(
            id="base",
            run_id=self.run_id,
            head=bootstrap_image,
            origin=bootstrap_image,
        )
        self._containers[branch.id] = container
        self._specs[branch.id] = spec

        if isinstance(source, RepoAtCommit):
            clone_cmd = (
                f"git clone -q -- {shlex.quote(source.url)} . "
                f"&& git checkout -q {shlex.quote(source.commit)}"
            )
            cloned = await self.run(branch, clone_cmd, timeout_s=300)
            if cloned.timed_out or cloned.exit_code != 0:
                raise RuntimeError(
                    f"git clone failed (exit {cloned.exit_code}, timed_out={cloned.timed_out}): "
                    f"{cloned.stderr_tail[-500:]}",
                )
            setup.append(source.install_cmd)

        for command in setup:
            receipt = await self.run(branch, command, timeout_s=1800)
            if receipt.timed_out or receipt.exit_code != 0:
                raise RuntimeError(
                    f"{install_error} (exit {receipt.exit_code}, timed_out={receipt.timed_out}): "
                    f"{receipt.stderr_tail[-500:]}",
                )

        _, stderr, code, timed_out, _, _ = await self._docker(
            "exec",
            container,
            "test",
            "-e",
            f"{spec.workdir}/.git",
            timeout_s=30,
        )
        if timed_out or code not in (0, 1):
            raise RuntimeError(
                f"checking repository metadata failed (exit {code}, timed_out={timed_out}): {_tail(stderr)}",
            )
        if code == 1:
            init_cmd = (
                "git init -q && git add -A && "
                "git -c user.name=receipts -c user.email=receipts@localhost "
                "commit -qm base --allow-empty"
            )
            initialized = await self.run(branch, init_cmd, timeout_s=120)
            if initialized.timed_out or initialized.exit_code != 0:
                raise RuntimeError(
                    f"git init failed (exit {initialized.exit_code}, timed_out={initialized.timed_out}): "
                    f"{initialized.stderr_tail[-500:]}",
                )
        self._anchors[branch.id] = await self._capture_anchor(container, spec)
        if source_image == branch.head and not setup:
            raise RuntimeError("Docker prepare did not capture the trusted runner")
        return branch

    async def run(self, branch: Branch, cmd: str, timeout_s: int) -> Receipt:
        stdout, stderr, code, timed_out, started, duration = await self._execute(
            branch,
            cmd,
            timeout_s,
        )
        image_after = await self._commit(self._container(branch))
        log_path = self._write_log(branch, stdout)
        tree_digest = await self._tree_digest(branch)
        return self._emit(
            branch,
            image_after,
            kind="command",
            cmd=cmd,
            exit_code=code,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            log_path=str(log_path),
            started_at=started,
            duration_s=duration,
            timed_out=timed_out,
            tree_digest=tree_digest,
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
        report_in_container = f"/opt/receipts/reports/{branch.id}-{seq}.xml"
        report_on_host = self.root / "reports" / f"{branch.id}-{seq}.xml"
        report_on_host.unlink(missing_ok=True)
        cmd = (
            f"{shlex.quote(spec.python)} -I /opt/receipts/receipts_pytest.py "
            f"{args} --junitxml={shlex.quote(report_in_container)} {PYTEST_FLAGS}"
        )
        stdout, stderr, code, timed_out, started, duration = await self._execute(
            branch,
            cmd,
            timeout_s,
            env_overrides={"PYTEST_ADDOPTS": "", "PYTEST_PLUGINS": ""},
        )
        report_bytes, _, report_code, report_timed_out, _, _ = await self._docker(
            "exec",
            self._container(branch),
            "cat",
            report_in_container,
            timeout_s=30,
        )
        if not report_timed_out and report_code == 0:
            report_on_host.write_bytes(report_bytes)
        junit = parse_junit(report_on_host if report_on_host.exists() else None)
        image_after = await self._commit(self._container(branch))
        log_path = self._write_log(branch, stdout)
        tree_digest = await self._tree_digest(branch)
        return self._emit(
            branch,
            image_after,
            kind=kind,
            cmd=cmd,
            exit_code=code,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            log_path=str(log_path),
            started_at=started,
            duration_s=duration,
            timed_out=timed_out,
            junit=junit,
            tree_digest=tree_digest,
        )

    async def write_file(self, branch: Branch, path: str, content: str) -> Receipt:
        started = _now()
        parts = self._path_parts(path)
        if parts is None:
            tree_digest = await self._tree_digest(branch)
            return self._emit(
                branch,
                branch.head,
                kind="write",
                path=path,
                exit_code=1,
                stderr_tail="refused: path is outside the repository",
                started_at=started,
                duration_s=(_now() - started).total_seconds(),
                tree_digest=tree_digest,
            )
        spec = self._spec(branch)
        anchor = self._anchor(branch)
        stdout, stderr, code, timed_out, _, _ = await self._docker(
            "exec",
            "-i",
            self._container(branch),
            spec.python,
            "-I",
            "-c",
            _WRITE_FILE,
            anchor.path,
            str(anchor.device),
            str(anchor.inode),
            *parts,
            input_data=content.encode(),
            timeout_s=120,
        )
        if timed_out:
            code = None
        image_after = await self._commit(self._container(branch))
        tree_digest = await self._tree_digest(branch)
        return self._emit(
            branch,
            image_after,
            kind="write",
            path=path,
            exit_code=code,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            stdout_sha256=hashlib.sha256(content.encode()).hexdigest(),
            started_at=started,
            duration_s=(_now() - started).total_seconds(),
            timed_out=timed_out,
            tree_digest=tree_digest,
        )

    async def read_file(self, branch: Branch, path: str, max_bytes: int) -> str:
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        parts = self._path_parts(path)
        if parts is None:
            return ""
        spec = self._spec(branch)
        anchor = self._anchor(branch)
        stdout, stderr, code, timed_out, _, _ = await self._docker(
            "exec",
            self._container(branch),
            spec.python,
            "-I",
            "-c",
            _READ_FILE,
            anchor.path,
            str(anchor.device),
            str(anchor.inode),
            str(max_bytes),
            *parts,
            timeout_s=30,
        )
        if code == 1 and not timed_out:
            return ""
        if timed_out or code != 0:
            raise RuntimeError(
                f"read file failed (exit {code}, timed_out={timed_out}): {_tail(stderr)}",
            )
        return stdout.decode(errors="replace")

    async def snapshot(self, branch: Branch) -> Receipt:
        cmd = (
            "git add -A && git -c user.name=receipts "
            "-c user.email=receipts@localhost commit -q --allow-empty -m \"receipts snapshot\" "
            "&& git rev-parse HEAD"
        )
        stdout, stderr, code, timed_out, started, duration = await self._execute(
            branch,
            cmd,
            120,
        )
        snapshot_sha = None
        if code == 0:
            lines = stdout.decode(errors="replace").splitlines()
            snapshot_sha = lines[-1].strip() if lines else None
        image_after = await self._commit(self._container(branch))
        tree_digest = await self._tree_digest(branch)
        return self._emit(
            branch,
            image_after,
            kind="command",
            cmd=cmd,
            exit_code=code,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            started_at=started,
            duration_s=duration,
            timed_out=timed_out,
            snapshot_sha=snapshot_sha,
            tree_digest=tree_digest,
        )

    async def checkpoint(self, branch: Branch) -> Checkpoint:
        parent = branch.head
        current_anchor = await self._capture_anchor(self._container(branch), self._spec(branch))
        if current_anchor != self._anchor(branch):
            raise RuntimeError("container workdir changed after prepare")
        image_id = await self._commit(self._container(branch))
        self._checkpoint_specs[image_id] = self._spec(branch)
        self._checkpoint_anchors[image_id] = current_anchor
        return Checkpoint(id=image_id, parent=parent, digest=image_id)

    async def fork(
        self,
        checkpoint: Checkpoint,
        n: int,
        prefix: str = "b",
    ) -> list[Branch]:
        if n < 0:
            raise ValueError("n must be non-negative")
        if checkpoint.id != checkpoint.digest or not _IMAGE_ID.fullmatch(checkpoint.id):
            raise ValueError("Docker checkpoints require one immutable sha256 image id")
        try:
            spec = self._checkpoint_specs[checkpoint.id]
        except KeyError as exc:
            raise RuntimeError(f"unknown Docker checkpoint: {checkpoint.id}") from exc
        branches: list[Branch] = []
        first = self._fork_next.get(prefix, 1)
        for index in range(first, first + n):
            branch_id = f"{prefix}{index}"
            name = f"{self.run_id}-{branch_id}"
            await self._start_container(checkpoint.id, name, spec)
            branch = Branch(
                id=branch_id,
                run_id=self.run_id,
                head=checkpoint.id,
                origin=checkpoint.id,
            )
            self._containers[branch.id] = name
            self._specs[branch.id] = spec
            anchor = await self._capture_anchor(name, spec)
            expected_anchor = self._checkpoint_anchors[checkpoint.id]
            if anchor.path != expected_anchor.path:
                raise RuntimeError("forked container workdir does not match its checkpoint")
            self._anchors[branch.id] = anchor
            branches.append(branch)
        self._fork_next[prefix] = first + n
        return branches

    async def release(self, branch: Branch) -> None:
        if branch.id in self._released_branches:
            return
        container = self._container(branch)
        await self._remove_created_container(container)
        self._containers.pop(branch.id, None)
        self._specs.pop(branch.id, None)
        self._anchors.pop(branch.id, None)
        self._released_branches.add(branch.id)

    async def patch(self, branch: Branch, snapshot_sha: str) -> Receipt:
        started = _now()
        token = uuid.uuid4().hex[:12]
        staging = self.root / "staging" / f"{branch.id}-{token}"
        agent_tree = self.root / "staging" / f"{branch.id}-{token}-agent"
        try:
            checkpoint_tree = await self._checkpoint_tree(branch.origin)
            await asyncio.to_thread(shutil.copytree, checkpoint_tree, staging, symlinks=True)
            archive_bytes = await self._workdir_archive(
                self._container(branch),
                self._spec(branch),
            )
            await asyncio.to_thread(self._extract_archive, archive_bytes, agent_tree)
            await asyncio.to_thread(mirror_worktree, agent_tree, staging)
        except (OSError, RuntimeError, shutil.Error, tarfile.TarError) as exc:
            for path in (agent_tree, staging):
                if path.exists():
                    await asyncio.to_thread(remove_path, path)
            message = f"trusted patch staging failed: {exc}".encode()
            return self._emit(
                branch,
                branch.head,
                kind="diff",
                cmd="compute patch in executor staging",
                exit_code=1,
                stderr_tail=_tail(message),
                stdout_sha256=hashlib.sha256(b"").hexdigest(),
                started_at=started,
                duration_s=(_now() - started).total_seconds(),
            )

        command = patch_command(self._git, snapshot_sha)
        display_cmd = f"compute patch in executor staging {staging.name}: {command}"
        stdout, stderr, code, timed_out, command_started, duration = await self._execute_host(
            staging,
            command,
            120,
            env_overrides=git_environment(self.root),
        )
        await asyncio.to_thread(remove_path, agent_tree)
        await asyncio.to_thread(remove_path, staging)
        if code != 0:
            return self._emit(
                branch,
                branch.head,
                kind="diff",
                cmd=display_cmd,
                exit_code=1,
                stdout_tail=_tail(stdout),
                stderr_tail=_tail(stderr),
                stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                started_at=command_started,
                duration_s=duration,
                timed_out=timed_out,
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
            branch.head,
            kind="diff",
            cmd=display_cmd,
            exit_code=0,
            stdout_tail=patch_text[-TAIL:],
            stderr_tail=_tail(stderr),
            stdout_sha256=summary.patch_sha256,
            started_at=command_started,
            duration_s=duration,
            timed_out=timed_out,
            diff=summary,
            dropped_paths=dropped,
        )

    async def apply_patch(self, branch: Branch, patch_text: str) -> Receipt:
        started = _now()
        digest = hashlib.sha256(patch_text.encode()).hexdigest()
        seq = self._seq.get(branch.id, 0) + 1
        patch_path = self.root / "patches" / f"{branch.id}-{seq}-apply.diff"
        patch_path.write_text(patch_text)
        container_patch = f"/opt/receipts/{branch.id}-{seq}-apply.diff"
        _, copy_stderr, copy_code, copy_timed_out, _, _ = await self._docker(
            "cp",
            str(patch_path),
            f"{self._container(branch)}:{container_patch}",
            timeout_s=120,
        )
        cmd = (
            "git update-index -q --refresh; "
            f"git apply {GIT_APPLY_FLAGS} {shlex.quote(container_patch)}"
        )
        if copy_timed_out or copy_code != 0:
            stdout = b""
            stderr = copy_stderr
            code = None if copy_timed_out else copy_code
            timed_out = copy_timed_out
            command_started = started
            duration = (_now() - started).total_seconds()
        elif not patch_text:
            stdout = b""
            stderr = b""
            code = 0
            timed_out = False
            command_started = started
            duration = (_now() - started).total_seconds()
        else:
            stdout, stderr, code, timed_out, command_started, duration = await self._execute(
                branch,
                cmd,
                120,
            )
        image_after = await self._commit(self._container(branch))
        tree_digest = await self._tree_digest(branch)
        return self._emit(
            branch,
            image_after,
            kind="apply",
            cmd=cmd,
            exit_code=code,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            patch_sha256=digest,
            started_at=command_started,
            duration_s=duration,
            timed_out=timed_out,
            tree_digest=tree_digest,
        )

    async def close(self) -> None:
        failures: list[str] = []
        remaining: list[str] = []
        for container in reversed(self._created_containers):
            _, stderr, code, timed_out, _, _ = await self._docker(
                "rm",
                "-f",
                container,
                timeout_s=60,
            )
            message = stderr.decode(errors="replace")
            if (timed_out or code != 0) and "No such container" not in message:
                remaining.append(container)
                failures.append(
                    f"{container} (exit {code}, timed_out={timed_out}): {message.strip()}",
                )
        self._created_containers = list(reversed(remaining))
        retained = set(remaining)
        removed_branches = {
            branch_id
            for branch_id, container in self._containers.items()
            if container not in retained
        }
        for branch_id in removed_branches:
            self._containers.pop(branch_id, None)
            self._specs.pop(branch_id, None)
            self._anchors.pop(branch_id, None)
        if failures:
            raise RuntimeError("failed to remove Docker containers: " + "; ".join(failures))
