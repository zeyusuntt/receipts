"""Classify what a patch touched. Used by the R4 patch_scope predicate.

Rules (deterministic, no model involved):
- Path categories use this precedence: outside, reserved, pytest_config,
  executable_artifact, shadow, test, source, other.
- outside: path escapes the repo (absolute or contains a `..` segment)
- reserved: interpreter startup hooks (sitecustomize.py, usercustomize.py) and
  entry_points.txt, which can register a pytest plugin from package metadata
  on sys.path; other package metadata is harmless and stays other
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
- symlink: decided from the diff header (mode 120000), not from the path,
  and overrides the path category
- unparseable: quoted or mismatched headers, and rename or copy metadata;
  it overrides every other category

The witness filter works at whole-file-block granularity. It keeps source and
other blocks only when no path segment starts with `.` and the path does not
contain `site-packages`. If any block is unparseable, it keeps nothing. Joining
the original `splitlines(keepends=True)` data preserves binary patch bodies and
`\\ No newline at end of file` markers.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import posixpath
import re
import sys

from receipts.models import ChangedFile, DiffSummary, FileCategory, PatchScope

_CONFIG = {
    "pytest.ini", "pytest.toml", ".pytest.toml", "tox.ini", "conftest.py",
    "pyproject.toml", "setup.cfg",
}
_EXECUTABLE_SUFFIXES = (".pyc", ".pyo", ".so", ".pyd", ".dylib", ".pth")
_RESERVED_BASENAMES = {"sitecustomize.py", "usercustomize.py", "entry_points.txt"}
_DIFF_HEADER_PREFIX = "diff --git "
_UNQUOTED_HEADER_PREFIX = "diff --git a/"
_UNPARSEABLE_METADATA = (
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
    "similarity index ",
    "dissimilarity index ",
)
_SYMLINK_MODE = re.compile(r"^(new file mode|old mode|new mode|deleted file mode) 120000$")


def _parse_header(line: str) -> tuple[str, str, bool] | None:
    if not line.startswith(_DIFF_HEADER_PREFIX):
        return None
    raw = line[len(_DIFF_HEADER_PREFIX):]
    if not line.startswith(_UNQUOTED_HEADER_PREFIX):
        return raw, raw, False
    rest = line[len(_UNQUOTED_HEADER_PREFIX):]
    doubled_path_length = len(rest) - len(" b/")
    if doubled_path_length < 0 or doubled_path_length % 2:
        return raw, raw, False
    path = rest[:doubled_path_length // 2]
    if not path or path.startswith('"') or rest != path + " b/" + path:
        return raw, raw, False
    return path, raw, True


def _split_blocks(patch_text: str) -> list[tuple[str, str, bool, list[str]]]:
    blocks: list[tuple[str, str, bool, list[str]]] = []
    path: str | None = None
    raw_header = ""
    parseable = False
    lines: list[str] = []
    for line in patch_text.splitlines(keepends=True):
        header = _parse_header(line.rstrip("\r\n"))
        if header is not None:
            if path is not None:
                blocks.append((path, raw_header, parseable, lines))
            path, raw_header, parseable = header
            lines = [line]
        elif path is not None:
            lines.append(line)
    if path is not None:
        blocks.append((path, raw_header, parseable, lines))
    return blocks


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
    if base in _RESERVED_BASENAMES:
        return "reserved"
    if base in _CONFIG:
        return "pytest_config"
    if base.endswith(_EXECUTABLE_SUFFIXES):
        return "executable_artifact"
    if "/" not in path and posixpath.splitext(base)[0] in protected_modules:
        return "shadow"
    if len(segments) == 1 and base == "__init__.py" and segments[0] in protected_modules:
        return "shadow"
    if any(seg in ("test", "tests") for seg in segments) or base.startswith("test_") or base.endswith("_test.py"):
        return "test"
    if base.endswith(".py"):
        return "source"
    return "other"


def _scope_top_level(path: str) -> tuple[str, str]:
    segments = path.split("/")
    if len(segments) >= 2 and segments[0] == "src":
        entry = f"src/{segments[1]}"
        name = segments[1]
    else:
        entry = segments[0]
        name = segments[0]
    if name.endswith(".py"):
        name = name[:-3]
    return entry, name


def scope_shadow(
    path: str,
    status: str | None,
    scope: PatchScope | None,
) -> bool:
    if scope is None or status != "added":
        return False
    top_level, name = _scope_top_level(path)
    return (
        top_level not in scope.c0_top_level
        and name in scope.protected_names
    )


def summarize_patch(
    patch_text: str,
    protected_modules: frozenset[str] = frozenset(),
) -> DiffSummary:
    files: list[ChangedFile] = []
    for path, raw_header, header_parseable, block_lines in _split_blocks(patch_text):
        added = deleted = 0
        symlink = False
        new_file = deleted_file = False
        metadata_parseable = True
        for raw_line in block_lines[1:]:
            line = raw_line.rstrip("\r\n")
            if line.startswith(_UNPARSEABLE_METADATA):
                metadata_parseable = False
            if line.startswith("new file mode "):
                new_file = True
            elif line.startswith("deleted file mode "):
                deleted_file = True
            if _SYMLINK_MODE.match(line):
                symlink = True
            elif line.startswith("+++") or line.startswith("---"):
                continue
            elif line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                deleted += 1

        parseable = header_parseable and metadata_parseable
        if not parseable:
            category: FileCategory = "unparseable"
            status = None
            path = raw_header
        else:
            category = "symlink" if symlink else categorize(path, protected_modules)
            if new_file:
                status = "added"
            elif deleted_file:
                status = "deleted"
            else:
                status = "modified"
        files.append(ChangedFile(
            path=path,
            added=added,
            deleted=deleted,
            category=category,
            status=status,
        ))
    return DiffSummary(files=files, patch_sha256=hashlib.sha256(patch_text.encode()).hexdigest())


def filter_patch(
    patch_text: str,
    protected_modules: frozenset[str] = frozenset(),
    spec_paths: frozenset[str] = frozenset(),
    scope: PatchScope | None = None,
) -> tuple[str, list[str]]:
    blocks = ["".join(lines) for _, _, _, lines in _split_blocks(patch_text)]
    summaries = [summarize_patch(block, protected_modules).files[0] for block in blocks]
    if any(summary.category == "unparseable" for summary in summaries):
        return "", [summary.path for summary in summaries]

    kept: list[str] = []
    dropped: list[str] = []
    for block, summary in zip(blocks, summaries, strict=True):
        path = summary.path
        category = summary.category
        hidden = any(segment.startswith(".") for segment in path.split("/"))
        if path in spec_paths:
            dropped.append(path)
        elif scope_shadow(path, summary.status, scope):
            dropped.append(path)
        elif category in ("source", "other") and not hidden and "site-packages" not in path:
            kept.append(block)
        else:
            dropped.append(path)
    return "".join(kept), dropped
