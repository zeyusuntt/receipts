"""A local implementation of the Executor protocol: one directory per branch,
subprocesses for commands, directory copies for checkpoints and forks, and
executor-owned reports and patch files outside every worktree.

Image ids here are provenance by sequence, not content hashes: every action
on a branch moves `branch.head` to a fresh id and the receipt records the
before and after ids, which is what the R5 chain check needs. Token Factory
gives real image uuids for the same fields.

Every command runs in its own process group and the whole group is killed
when the command ends or times out, so a worker cannot leave a sleeper
process behind that later tampers with verification.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import shutil
import signal
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from receipts.junit import parse_junit
from receipts.models import Branch, Checkpoint, Receipt, ReceiptKind
from receipts.patchscope import default_protected_modules, filter_patch, summarize_patch
from receipts.sandbox.protocol import PYTEST_BOOTSTRAP, PYTEST_FLAGS, RepoAtCommit, Source
from receipts.sandbox.sink import ReceiptSink

TAIL = 6000


class CheckpointTampered(Exception):
    def __init__(self, checkpoint_id: str) -> None:
        super().__init__(f"checkpoint {checkpoint_id} was modified after prepare")
        self.checkpoint_id = checkpoint_id
        self.patch_receipt: Receipt | None = None


def _tail(data: bytes) -> str:
    return data.decode(errors="replace")[-TAIL:]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _checkpoint_manifest_digest(entries: list[tuple[str, int, str]]) -> str:
    serialized = json.dumps(sorted(entries), ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _checkpoint_digest(root: Path) -> str:
    entries: list[tuple[str, int, str]] = []

    def visit(directory: Path) -> None:
        for path in directory.iterdir():
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                content = os.fsencode(os.readlink(path))
            elif stat.S_ISREG(mode):
                content = path.read_bytes()
            elif stat.S_ISDIR(mode):
                content = b""
            else:
                raise OSError(f"unsupported checkpoint entry: {path}")
            entries.append((path.relative_to(root).as_posix(), mode, hashlib.sha256(content).hexdigest()))
            if stat.S_ISDIR(mode):
                visit(path)

    visit(root)
    return _checkpoint_manifest_digest(entries)


def _remove_path(path: Path) -> None:
    mode = path.lstat().st_mode
    if stat.S_ISDIR(mode):
        path.chmod(stat.S_IMODE(mode) | stat.S_IRWXU, follow_symlinks=False)
        for child in path.iterdir():
            _remove_path(child)
        path.rmdir()
    else:
        path.unlink()


def _mirror_entry(source: Path, destination: Path) -> None:
    source_mode = source.lstat().st_mode
    destination_exists = os.path.lexists(destination)
    if stat.S_ISLNK(source_mode):
        if destination_exists:
            _remove_path(destination)
        destination.symlink_to(os.readlink(source))
        shutil.copystat(source, destination, follow_symlinks=False)
        return
    if stat.S_ISDIR(source_mode):
        if destination_exists and not stat.S_ISDIR(destination.lstat().st_mode):
            _remove_path(destination)
            destination_exists = False
        if not destination_exists:
            destination.mkdir()
        destination.chmod(destination.lstat().st_mode | stat.S_IRWXU, follow_symlinks=False)
        source_names = {child.name for child in source.iterdir()}
        for child in destination.iterdir():
            if child.name not in source_names:
                _remove_path(child)
        for child in source.iterdir():
            _mirror_entry(child, destination / child.name)
        shutil.copystat(source, destination, follow_symlinks=False)
        return
    if stat.S_ISREG(source_mode):
        if destination_exists:
            _remove_path(destination)
        shutil.copy2(source, destination, follow_symlinks=False)
        return
    raise OSError(f"unsupported worktree entry: {source}")


def _mirror_worktree(source: Path, destination: Path) -> None:
    source_names = {child.name for child in source.iterdir() if child.name != ".git"}
    for child in destination.iterdir():
        if child.name != ".git" and child.name not in source_names:
            _remove_path(child)
    for child in source.iterdir():
        if child.name != ".git":
            _mirror_entry(child, destination / child.name)


class LocalExecutor:
    def __init__(self, root: Path, sink: ReceiptSink, run_id: str) -> None:
        self.root = root
        self.sink = sink
        self.run_id = run_id
        self._seq: dict[str, int] = {}
        self._dirs: dict[str, Path] = {}  # branch id or checkpoint id -> directory
        self._checkpoint_digests: dict[str, str] = {}
        self._fork_next: dict[str, int] = {}
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
        (self.root / "reports").mkdir(exist_ok=True)
        (self.root / "patches").mkdir(exist_ok=True)
        tools = self.root / "tools"
        tools.mkdir(exist_ok=True)
        self._pytest_runner = tools / "receipts_pytest.py"
        self._pytest_runner.write_text(PYTEST_BOOTSTRAP)

    # ----- helpers -----

    def workdir(self, branch: Branch) -> Path:
        return self._dirs[branch.id]

    @staticmethod
    def _new_image() -> str:
        return f"local-{uuid.uuid4().hex[:12]}"

    def _emit(self, branch: Branch, **fields) -> Receipt:
        """Assign the next sequence number and image id, build the receipt
        with every field final, write it once, return it."""
        seq = self._seq.get(branch.id, 0) + 1
        self._seq[branch.id] = seq
        before, after = branch.head, self._new_image()
        branch.head = after
        r = Receipt(receipt_id=f"{branch.id}-{seq}", seq=seq, branch_id=branch.id,
                    image_before=before, image_after=after, **fields)
        self.sink.write(r)
        return r

    def _safe_path(self, branch: Branch, path: str) -> Path | None:
        base = self.workdir(branch).resolve()
        target = (base / path).resolve()
        return target if target == base or base in target.parents else None

    def _assert_checkpoint_intact(self, checkpoint_id: str, claimed_digest: str | None = None) -> None:
        expected = self._checkpoint_digests.get(checkpoint_id)
        checkpoint_dir = self._dirs.get(checkpoint_id)
        if expected is None or checkpoint_dir is None or claimed_digest not in (None, expected):
            raise CheckpointTampered(checkpoint_id)
        try:
            actual = _checkpoint_digest(checkpoint_dir)
        except OSError as exc:
            raise CheckpointTampered(checkpoint_id) from exc
        if actual != expected:
            raise CheckpointTampered(checkpoint_id)

    async def _execute(
        self,
        workdir: Path,
        cmd: str,
        timeout_s: int,
        env_overrides: dict[str, str] | None = None,
    ) -> tuple[bytes, bytes, int | None, bool, datetime, float]:
        env = {
            "PATH": f"{workdir / '.venv' / 'bin'}:{Path(sys.executable).parent}:{os.environ.get('PATH', '')}",
            "HOME": str(self.root), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
        }
        if env_overrides:
            env.update(env_overrides)
        started = _now()
        proc = await asyncio.create_subprocess_exec(
            str(self._bash), "-c", cmd, cwd=workdir, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            code: int | None = proc.returncode
        except asyncio.TimeoutError:
            timed_out, code = True, None
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # leader not yet reaped, so the pgid is still ours
            except ProcessLookupError:
                pass
            stdout, stderr = await proc.communicate()  # collect what was produced, reap the leader
        else:
            # Normal completion: the leader is reaped; kill any background children it left in the group.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return stdout, stderr, code, timed_out, started, (_now() - started).total_seconds()

    # ----- protocol -----

    async def prepare(self, source: Source) -> Branch:
        assert isinstance(source, RepoAtCommit)
        workdir = self.root / "base"
        clone = await asyncio.create_subprocess_exec("git", "clone", "-q", source.url, str(workdir),
                                                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await clone.communicate()
        if clone.returncode != 0:
            raise RuntimeError(f"git clone failed: {err.decode(errors='replace')}")
        co = await asyncio.create_subprocess_exec("git", "checkout", "-q", source.commit, cwd=workdir,
                                                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await co.communicate()
        if co.returncode != 0:
            raise RuntimeError(f"git checkout failed: {err.decode(errors='replace')}")
        origin = self._new_image()
        branch = Branch(id="base", run_id=self.run_id, head=origin, origin=origin)
        self._dirs[branch.id] = workdir
        install = await self.run(branch, source.install_cmd, timeout_s=1800)
        if install.timed_out or install.exit_code != 0:
            raise RuntimeError(f"install command failed (exit {install.exit_code}, timed_out={install.timed_out}): {install.stderr_tail[-500:]}")
        return branch

    async def snapshot(self, branch: Branch) -> Receipt:
        cmd = ('git add -A && git -c user.name=receipts '
               '-c user.email=receipts@localhost commit -q --allow-empty -m "receipts snapshot" '
               '&& git rev-parse HEAD')
        stdout, stderr, code, timed_out, started, duration = await self._execute(self.workdir(branch), cmd, 120)
        snapshot_sha = None
        if code == 0:
            lines = stdout.decode(errors="replace").splitlines()
            snapshot_sha = lines[-1].strip() if lines else None
        return self._emit(branch, kind="command", cmd=cmd, exit_code=code,
                          stdout_tail=_tail(stdout), stderr_tail=_tail(stderr),
                          stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                          started_at=started, duration_s=duration, timed_out=timed_out,
                          snapshot_sha=snapshot_sha)

    async def checkpoint(self, branch: Branch) -> Checkpoint:
        cp_id = f"ckpt-{uuid.uuid4().hex[:12]}"
        dest = self.root / cp_id
        await asyncio.to_thread(shutil.copytree, self.workdir(branch), dest, symlinks=True)
        digest = await asyncio.to_thread(_checkpoint_digest, dest)
        self._dirs[cp_id] = dest
        self._checkpoint_digests[cp_id] = digest
        return Checkpoint(id=cp_id, parent=branch.head, digest=digest)

    async def fork(self, checkpoint: Checkpoint, n: int, prefix: str = "b") -> list[Branch]:
        await asyncio.to_thread(self._assert_checkpoint_intact, checkpoint.id, checkpoint.digest)
        branches: list[Branch] = []
        first = self._fork_next.get(prefix, 1)
        for i in range(first, first + n):
            bid = f"{prefix}{i}"
            dest = self.root / bid
            await asyncio.to_thread(shutil.copytree, self._dirs[checkpoint.id], dest, symlinks=True)
            self._dirs[bid] = dest
            branches.append(Branch(id=bid, run_id=self.run_id, head=checkpoint.id, origin=checkpoint.id))
        self._fork_next[prefix] = first + n
        return branches

    async def run(self, branch: Branch, cmd: str, timeout_s: int) -> Receipt:
        stdout, stderr, code, timed_out, started, duration = await self._execute(self.workdir(branch), cmd, timeout_s)
        return self._emit(branch, kind="command", cmd=cmd, exit_code=code,
                          stdout_tail=_tail(stdout), stderr_tail=_tail(stderr),
                          stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                          started_at=started, duration_s=duration, timed_out=timed_out)

    async def run_pytest(self, branch: Branch, args: str, timeout_s: int, kind: ReceiptKind = "command") -> Receipt:
        seq = self._seq.get(branch.id, 0) + 1
        report = self.root / "reports" / f"{branch.id}-{seq}.xml"
        runner = shlex.quote(str(self._pytest_runner))
        cmd = f"python -I {runner} {args} {PYTEST_FLAGS} --junitxml={shlex.quote(str(report))}"
        stdout, stderr, code, timed_out, started, duration = await self._execute(self.workdir(branch), cmd, timeout_s)
        junit = parse_junit(report if report.exists() else None)
        return self._emit(branch, kind=kind, cmd=cmd, exit_code=code,
                          stdout_tail=_tail(stdout), stderr_tail=_tail(stderr),
                          stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                          started_at=started, duration_s=duration, timed_out=timed_out, junit=junit)

    async def read_file(self, branch: Branch, path: str, max_bytes: int) -> str:
        target = self._safe_path(branch, path)
        if target is None or not target.is_file():
            return ""
        return target.read_bytes()[:max_bytes].decode(errors="replace")

    async def write_file(self, branch: Branch, path: str, content: str) -> Receipt:
        started = _now()
        target = self._safe_path(branch, path)
        if target is None:
            return self._emit(branch, kind="write", path=path, exit_code=1,
                              stderr_tail="refused: path is outside the repository",
                              started_at=started, duration_s=0.0)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return self._emit(branch, kind="write", path=path, exit_code=0,
                          stdout_sha256=hashlib.sha256(content.encode()).hexdigest(),
                          started_at=started, duration_s=(_now() - started).total_seconds())

    async def patch(self, branch: Branch, snapshot_sha: str) -> Receipt:
        started = _now()
        staging = self.root / "staging" / f"{branch.id}-{uuid.uuid4().hex[:12]}"
        origin = self._dirs.get(branch.origin, self.workdir(branch))
        if branch.origin in self._checkpoint_digests:
            try:
                await asyncio.to_thread(self._assert_checkpoint_intact, branch.origin)
            except CheckpointTampered as exc:
                message = str(exc).encode()
                exc.patch_receipt = self._emit(
                    branch,
                    kind="diff",
                    cmd="compute patch in executor staging",
                    exit_code=1,
                    stderr_tail=_tail(message),
                    stdout_sha256=hashlib.sha256(b"").hexdigest(),
                    started_at=started,
                    duration_s=(_now() - started).total_seconds(),
                )
                raise
        try:
            await asyncio.to_thread(shutil.copytree, origin, staging, symlinks=True)
            await asyncio.to_thread(_mirror_worktree, self.workdir(branch), staging)
        except (OSError, shutil.Error) as exc:
            if staging.exists():
                await asyncio.to_thread(_remove_path, staging)
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
        git = (
            f"{shlex.quote(str(self._git))} -c core.hooksPath=/dev/null "
            "-c core.attributesFile=/dev/null "
            "-c diff.external= -c core.quotePath=false"
        )
        command = (
            f"{git} add -A && {git} diff --cached --binary --no-ext-diff "
            f"--no-textconv --no-renames {shlex.quote(snapshot_sha)}"
        )
        display_cmd = f"compute patch in executor staging {staging.name}: {command}"
        git_env = {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "HOME": str(self.root),
            "PATH": os.defpath,
        }
        stdout, stderr, code, timed_out, command_started, duration = await self._execute(
            staging,
            command,
            120,
            env_overrides=git_env,
        )
        await asyncio.to_thread(_remove_path, staging)
        if code != 0:
            return self._emit(branch, kind="diff", cmd=display_cmd, exit_code=1,
                              stdout_tail=_tail(stdout), stderr_tail=_tail(stderr),
                              stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                              started_at=command_started, duration_s=duration, timed_out=timed_out)
        patch_text = stdout.decode(errors="replace")
        seq = self._seq.get(branch.id, 0) + 1
        patch_path = self.root / "patches" / f"{branch.id}-{seq}-full.diff"
        patch_path.write_text(patch_text)
        summary = summarize_patch(patch_text, self._protected_modules).model_copy(
            update={"patch_path": str(patch_path)},
        )
        _, dropped = filter_patch(patch_text, self._protected_modules)
        return self._emit(branch, kind="diff", cmd=display_cmd, exit_code=0,
                          stdout_tail=patch_text[-TAIL:], stderr_tail=_tail(stderr),
                          stdout_sha256=summary.patch_sha256, started_at=command_started,
                          duration_s=duration, timed_out=timed_out, diff=summary,
                          dropped_paths=dropped)

    async def apply_patch(self, branch: Branch, patch_text: str) -> Receipt:
        started = _now()
        digest = hashlib.sha256(patch_text.encode()).hexdigest()
        if branch.origin in self._checkpoint_digests:
            try:
                await asyncio.to_thread(self._assert_checkpoint_intact, branch.origin)
            except CheckpointTampered as exc:
                return self._emit(
                    branch,
                    kind="apply",
                    cmd="apply filtered patch to witness",
                    exit_code=1,
                    stderr_tail=str(exc),
                    patch_sha256=digest,
                    started_at=started,
                    duration_s=(_now() - started).total_seconds(),
                )
        seq = self._seq.get(branch.id, 0) + 1
        patch_path = self.root / "patches" / f"{branch.id}-{seq}-apply.diff"
        patch_path.write_text(patch_text)
        # Checkpoints and forks are directory copies, so the copied git index carries stale
        # stat data and `git apply --index` refuses with "does not match index". Refresh first.
        # Found by the Sep 30 dry run of this plan; Token Factory images are copies too.
        cmd = f"git update-index -q --refresh; git apply --index {shlex.quote(str(patch_path))}"
        if not patch_text:
            return self._emit(branch, kind="apply", cmd=cmd, exit_code=0,
                              patch_sha256=digest, started_at=started,
                              duration_s=(_now() - started).total_seconds())
        stdout, stderr, code, timed_out, command_started, duration = await self._execute(
            self.workdir(branch), cmd, 120,
        )
        return self._emit(branch, kind="apply", cmd=cmd, exit_code=code,
                          stdout_tail=_tail(stdout), stderr_tail=_tail(stderr),
                          stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                          patch_sha256=digest, started_at=command_started,
                          duration_s=duration, timed_out=timed_out)
