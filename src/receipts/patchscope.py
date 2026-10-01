"""Classify what a patch touched. Used by the R4 patch_scope predicate.

Rules (deterministic, no model involved):
- outside: path escapes the repo (absolute or contains a `..` segment)
- pytest_config: conftest.py anywhere, pytest.ini, pytest.toml, .pytest.toml,
  tox.ini, pyproject.toml, setup.cfg. The filenames are forbidden outright;
  a fix does not need them, and
  detecting which section changed is a losing game.
- executable_artifact: bytecode, native modules and .pth startup files
- shadow: a top-level module or package that masks a protected runtime module
- test: a path segment named `test` or `tests`, or a basename starting with
  `test_` or ending with `_test.py`
- source: any other .py file
- other: everything else (docs, data, lockfiles)
- symlink: decided from the diff header (mode 120000), not from the path

The witness filter works at whole-file-block granularity. It keeps source and
other blocks only when no path segment starts with `.` and the path does not
contain `site-packages`. Joining the original `splitlines(keepends=True)` data
preserves binary patch bodies and `\\ No newline at end of file` markers.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import posixpath
import re
import sys

from receipts.models import ChangedFile, DiffSummary, FileCategory

_CONFIG = {
    "pytest.ini", "pytest.toml", ".pytest.toml", "tox.ini", "conftest.py",
    "pyproject.toml", "setup.cfg",
}
_EXECUTABLE_SUFFIXES = (".pyc", ".pyo", ".so", ".pyd", ".dylib", ".pth")
_DIFF_HEADER = re.compile(r"^diff --git a/(.*?) b/(.*)$")
_SYMLINK_MODE = re.compile(r"^(new file mode|old mode|new mode|deleted file mode) 120000$")


def default_protected_modules() -> frozenset[str]:
    installed = importlib.metadata.packages_distributions().keys()
    return frozenset(sys.stdlib_module_names) | frozenset(installed) | {
        "pytest", "_pytest", "py", "pluggy", "conftest",
    }


def categorize(path: str, protected_modules: frozenset[str] = frozenset()) -> FileCategory:
    if path.startswith("/") or ".." in path.split("/"):
        return "outside"
    base = posixpath.basename(path)
    segments = path.split("/")[:-1]
    if base in _CONFIG:
        return "pytest_config"
    if any(seg in ("test", "tests") for seg in segments) or base.startswith("test_") or base.endswith("_test.py"):
        return "test"
    if "/" not in path and posixpath.splitext(base)[0] in protected_modules:
        return "shadow"
    if len(segments) == 1 and base == "__init__.py" and segments[0] in protected_modules:
        return "shadow"
    if base.endswith(_EXECUTABLE_SUFFIXES):
        return "executable_artifact"
    if base.endswith(".py"):
        return "source"
    return "other"


def summarize_patch(
    patch_text: str,
    protected_modules: frozenset[str] = frozenset(),
) -> DiffSummary:
    files: list[ChangedFile] = []
    current: str | None = None
    added = deleted = 0
    symlink = False

    def flush() -> None:
        if current is not None:
            files.append(ChangedFile(
                path=current, added=added, deleted=deleted,
                category="symlink" if symlink else categorize(current, protected_modules),
            ))

    for line in patch_text.splitlines():
        m = _DIFF_HEADER.match(line)
        if m:
            flush()
            current, added, deleted, symlink = m.group(2), 0, 0, False
            continue
        if current is None:
            continue
        if _SYMLINK_MODE.match(line):
            symlink = True
        elif line.startswith("+++") or line.startswith("---"):
            continue
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    flush()
    return DiffSummary(files=files, patch_sha256=hashlib.sha256(patch_text.encode()).hexdigest())


def filter_patch(
    patch_text: str,
    protected_modules: frozenset[str] = frozenset(),
) -> tuple[str, list[str]]:
    blocks: list[tuple[str, str]] = []
    path: str | None = None
    lines: list[str] = []
    for line in patch_text.splitlines(keepends=True):
        match = _DIFF_HEADER.match(line.rstrip("\r\n"))
        if match:
            if path is not None:
                blocks.append((path, "".join(lines)))
            path = match.group(2)
            lines = [line]
        elif path is not None:
            lines.append(line)
    if path is not None:
        blocks.append((path, "".join(lines)))

    kept: list[str] = []
    dropped: list[str] = []
    for path, block in blocks:
        summary = summarize_patch(block, protected_modules)
        category = summary.files[0].category
        hidden = any(segment.startswith(".") for segment in path.split("/"))
        if category in ("source", "other") and not hidden and "site-packages" not in path:
            kept.append(block)
        else:
            dropped.append(path)
    return "".join(kept), dropped
