"""Build one bounded, structured repair plan from repository evidence."""

from __future__ import annotations

import ast
import json
import logging
import posixpath
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel

from receipts.cost import TokenUsage
from receipts.llm import ModelClient
from receipts.models import Baseline, Branch, Receipt, bounded_target_failure_text
from receipts.sandbox.protocol import Executor


SYSTEM_PROMPT = """\
You plan the smallest source change that can resolve the reported issue.
The tests named by the user are the specification and are read-only.
Propose the smallest change that satisfies those tests without changing tests or pytest configuration.
Name only files that exist in the repository context, using repository-relative paths.
"""

_LIST_FILES_COMMAND = "git ls-files -z"
_LIST_FILES_TIMEOUT_S = 30
_MAX_TREE_PATHS = 400
_MAX_IMPORTED_FILES = 5
_MAX_FILE_BYTES = 12_000
_SOURCE_ROOTS = {"lib", "src"}

logger = logging.getLogger(__name__)


class Plan(BaseModel):
    hypothesis: str
    files_to_edit: list[str]
    approach: str
    usage: TokenUsage | None = None
    finish_reason: str | None = None

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Keep provider bookkeeping out of the planner's response contract."""
        schema = super().model_json_schema(*args, **kwargs)
        properties = schema.get("properties", {})
        properties.pop("usage", None)
        properties.pop("finish_reason", None)
        schema.pop("$defs", None)
        return schema


def _full_stdout(receipt: Receipt) -> str:
    if receipt.log_path is not None:
        try:
            return Path(receipt.log_path).read_bytes().decode(errors="replace")
        except OSError:
            pass
    return receipt.stdout_tail


def _normalize_repo_path(raw_path: str) -> str | None:
    candidate = PurePosixPath(raw_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    normalized = posixpath.normpath(raw_path)
    if normalized in {"", "."} or normalized.startswith("../"):
        return None
    return normalized


def _module_names(path: str) -> list[str]:
    file_path = PurePosixPath(path)
    if file_path.suffix != ".py":
        return []
    if file_path.name == "__init__.py":
        parts = file_path.parent.parts
    else:
        parts = file_path.with_suffix("").parts
    if not parts:
        return []
    names = [".".join(parts)]
    if parts[0] in _SOURCE_ROOTS and len(parts) > 1:
        names.append(".".join(parts[1:]))
    return names


def _module_index(tracked_paths: list[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for path in sorted(tracked_paths):
        for module_name in _module_names(path):
            index.setdefault(module_name, path)
    return index


def _absolute_import(module: str | None, level: int, test_path: str) -> str:
    if level == 0:
        return module or ""
    package = list(PurePosixPath(test_path).parent.parts)
    remove = level - 1
    if remove > len(package):
        return ""
    if remove:
        package = package[:-remove]
    if module:
        package.extend(module.split("."))
    return ".".join(package)


def _imported_modules(source: str, test_path: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        nodes: list[ast.AST] = []
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            try:
                statement = ast.parse(stripped)
            except SyntaxError:
                continue
            nodes.extend(statement.body)
    else:
        nodes = list(ast.walk(tree))

    modules: list[str] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        base = _absolute_import(node.module, node.level, test_path)
        if base:
            modules.append(base)
        for alias in node.names:
            if alias.name != "*":
                modules.append(f"{base}.{alias.name}" if base else alias.name)
    return list(dict.fromkeys(modules))


def _source_paths(
    test_files: list[tuple[str, str]],
    tracked_paths: list[str],
) -> list[str]:
    index = _module_index(tracked_paths)
    test_paths = {path for path, _ in test_files}
    sources: list[str] = []
    for test_path, content in test_files:
        for module_name in _imported_modules(content, test_path):
            source_path = index.get(module_name)
            if source_path is None or source_path in test_paths or source_path in sources:
                continue
            sources.append(source_path)
            if len(sources) == _MAX_IMPORTED_FILES:
                return sources
    return sources


def _prompt(
    issue: str,
    baseline: Baseline,
    spec_tests: list[str],
    tree_paths: list[str],
    test_files: list[tuple[str, str]],
    source_files: list[tuple[str, str]],
) -> str:
    failure_text = bounded_target_failure_text(
        baseline.target,
        baseline.target_failure_text,
    )
    baseline_summary = {
        "targets": [
            {
                "id": target,
                "outcomes": [run.outcome(target) for run in baseline.runs],
                "failure_text": failure_text[target],
            }
            for target in baseline.target
        ],
        "counts": {
            "collected": len(baseline.collected_ids),
            "protected": len(baseline.protected),
            "unstable": len(baseline.unstable),
            "skipped": len(baseline.skipped_ids),
        },
    }
    sections = [
        f"<issue>\n{issue}\n</issue>",
        "<specification_tests>\n" + "\n".join(spec_tests) + "\n</specification_tests>",
        f"<baseline>\n{json.dumps(baseline_summary, indent=2)}\n</baseline>",
        "<tracked_files>\n" + "\n".join(tree_paths) + "\n</tracked_files>",
    ]
    for path, content in test_files:
        sections.append(f'<specification_test_file path="{path}">\n{content}\n</specification_test_file>')
    for path, content in source_files:
        sections.append(f'<imported_source_file path="{path}">\n{content}\n</imported_source_file>')
    return "\n\n".join(sections)


async def make_plan(
    model: ModelClient,
    ex: Executor,
    branch: Branch,
    issue: str,
    baseline: Baseline,
    spec_tests: list[str],
) -> tuple[Plan, list[Receipt]]:
    listing = await ex.run(
        branch,
        _LIST_FILES_COMMAND,
        timeout_s=_LIST_FILES_TIMEOUT_S,
    )
    if listing.timed_out or listing.exit_code != 0:
        raise RuntimeError(
            "could not list tracked files "
            f"(exit {listing.exit_code}, timed_out={listing.timed_out}): "
            f"{listing.stderr_tail[-500:]}",
        )

    tracked_paths = list(
        dict.fromkeys(path for path in _full_stdout(listing).split("\0") if path),
    )
    tracked_set = set(tracked_paths)
    tree_paths = sorted(
        tracked_paths,
        key=lambda path: (path.count("/"), path),
    )[:_MAX_TREE_PATHS]

    test_paths: list[str] = []
    for node_id in spec_tests:
        normalized = _normalize_repo_path(node_id.split("::", 1)[0])
        if normalized is not None and normalized not in test_paths:
            test_paths.append(normalized)
    test_files = [
        (path, await ex.read_file(branch, path, max_bytes=_MAX_FILE_BYTES))
        for path in test_paths
    ]
    imported_paths = _source_paths(test_files, tracked_paths)
    source_files = [
        (path, await ex.read_file(branch, path, max_bytes=_MAX_FILE_BYTES))
        for path in imported_paths
    ]

    plan = await model.complete_json(
        SYSTEM_PROMPT,
        _prompt(issue, baseline, spec_tests, tree_paths, test_files, source_files),
        Plan,
    )

    kept: list[str] = []
    dropped: list[str] = []
    for proposed in plan.files_to_edit:
        normalized = _normalize_repo_path(proposed)
        if normalized is None or normalized not in tracked_set:
            dropped.append(proposed)
        else:
            kept.append(normalized)
    if dropped:
        rendered = json.dumps(dropped, ensure_ascii=True)
        logger.warning("planner dropped nonexistent files: %s", rendered)
        plan = plan.model_copy(
            update={
                "files_to_edit": kept,
                "approach": (
                    f"{plan.approach.rstrip()}\n\n"
                    f"Planner dropped nonexistent files: {rendered}"
                ),
            },
        )
    elif kept != plan.files_to_edit:
        plan = plan.model_copy(update={"files_to_edit": kept})

    return plan, [listing]
