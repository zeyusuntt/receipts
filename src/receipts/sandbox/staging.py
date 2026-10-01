"""Trusted host-side staging helpers used to compute repository patches.

The agent worktree is mirrored onto an executor-owned copy of the checkpoint.
Git then runs only in that copy with system, global, hook, attribute, external
diff, text conversion, and rename behavior constrained by the executor.
"""

from __future__ import annotations

import os
import shlex
import shutil
import stat
from pathlib import Path


def remove_path(path: Path) -> None:
    mode = path.lstat().st_mode
    if stat.S_ISDIR(mode):
        path.chmod(stat.S_IMODE(mode) | stat.S_IRWXU, follow_symlinks=False)
        for child in path.iterdir():
            remove_path(child)
        path.rmdir()
    else:
        path.unlink()


def _mirror_entry(source: Path, destination: Path) -> None:
    source_mode = source.lstat().st_mode
    destination_exists = os.path.lexists(destination)
    if stat.S_ISLNK(source_mode):
        if destination_exists:
            remove_path(destination)
        destination.symlink_to(os.readlink(source))
        shutil.copystat(source, destination, follow_symlinks=False)
        return
    if stat.S_ISDIR(source_mode):
        if destination_exists and not stat.S_ISDIR(destination.lstat().st_mode):
            remove_path(destination)
            destination_exists = False
        if not destination_exists:
            destination.mkdir()
        destination.chmod(destination.lstat().st_mode | stat.S_IRWXU, follow_symlinks=False)
        source_names = {child.name for child in source.iterdir()}
        for child in destination.iterdir():
            if child.name not in source_names:
                remove_path(child)
        for child in source.iterdir():
            _mirror_entry(child, destination / child.name)
        shutil.copystat(source, destination, follow_symlinks=False)
        return
    if stat.S_ISREG(source_mode):
        if destination_exists:
            remove_path(destination)
        shutil.copy2(source, destination, follow_symlinks=False)
        return
    raise OSError(f"unsupported worktree entry: {source}")


def mirror_worktree(source: Path, destination: Path) -> None:
    source_names = {child.name for child in source.iterdir() if child.name != ".git"}
    for child in destination.iterdir():
        if child.name != ".git" and child.name not in source_names:
            remove_path(child)
    for child in source.iterdir():
        if child.name != ".git":
            _mirror_entry(child, destination / child.name)


def git_command(git: Path, *args: str) -> str:
    hardened_git = (
        f"{shlex.quote(str(git))} -c core.hooksPath=/dev/null "
        "-c core.attributesFile=/dev/null "
        "-c diff.external= -c core.quotePath=false"
    )
    return " ".join((hardened_git, *(shlex.quote(arg) for arg in args)))


def patch_command(git: Path, snapshot_sha: str) -> str:
    diff = git_command(
        git,
        "diff",
        "--cached",
        "--binary",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        snapshot_sha,
    )
    return (
        f"{git_command(git, 'add', '-A')} && "
        f"{diff}"
    )


def git_environment(root: Path) -> dict[str, str]:
    return {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "HOME": str(root),
        "PATH": os.defpath,
    }
