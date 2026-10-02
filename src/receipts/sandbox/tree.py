"""Canonical worktree digest shared by remote executors."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath


def tree_digest_ignores(path: str) -> bool:
    return ".git" in PurePosixPath(path).parts


def tree_digest(root: Path) -> str:
    entries: list[tuple[str, int, str]] = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(root)
        names[:] = sorted(
            name
            for name in names
            if not tree_digest_ignores((relative_directory / name).as_posix())
        )
        for filename in sorted(
            name
            for name in filenames
            if not tree_digest_ignores((relative_directory / name).as_posix())
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
