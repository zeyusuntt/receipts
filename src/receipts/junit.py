"""Turn a pytest junit xml file into a JunitSummary.

pytest must be run with `-o junit_family=xunit1` so each testcase carries a
`file` attribute; the module part of `classname` is derived from it and the
remaining dotted components are the class chain.

A testcase with any failure or error child counts as a failed outcome, even if
another reporting surface describes its parent as passed. Failures and errors
remain separate in the returned summary.
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from receipts.models import JunitSummary


_FAILURE_TEXT_ENTRY_LIMIT = 2_000
_FAILURE_TEXT_TOTAL_LIMIT = 60_000
_ANSI_ESCAPE = re.compile(
    r"(?:\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x9b[0-?]*[ -/]*[@-~])",
)


def _failure_text(element: ET.Element) -> str:
    parts = [element.get("message", "").strip(), "".join(element.itertext()).strip()]
    combined = "\n".join(part for part in parts if part)
    # pytest replaces XML-illegal ESC bytes with the literal token ``#x1B``.
    plain = _ANSI_ESCAPE.sub("", combined.replace("#x1B", "\x1b"))
    if len(plain) <= _FAILURE_TEXT_ENTRY_LIMIT:
        return plain
    marker = "[...]"
    return marker + plain[-(_FAILURE_TEXT_ENTRY_LIMIT - len(marker)):]


def node_id(file: str, classname: str, name: str) -> str:
    module = file[:-3] if file.endswith(".py") else file
    module_parts = module.split("/")
    parts = classname.split(".")
    classes = parts[len(module_parts):] if parts[: len(module_parts)] == module_parts else parts
    return "::".join([file, *classes, name])


def parse_junit(path: Path | None) -> JunitSummary | None:
    if path is None:
        return None
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    passed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []
    skipped: list[str] = []
    collection_errors: list[str] = []
    collection_failure_text: list[tuple[str, str]] = []
    testcase_failure_text: list[tuple[str, str]] = []
    # The trusted runner records where pytest's rootdir and invocation dir are. pytest
    # writes junit paths relative to the rootdir but prints node ids (and SWE-rebench
    # records them) relative to the invocation dir, so rebase to the printed form.
    properties = {prop.get("name"): prop.get("value") for prop in root.iter("property")}
    rootdir = properties.get("receipts_rootdir")
    invocation = properties.get("receipts_invocation_dir")

    def rebase(file: str) -> str:
        if not file or not rootdir or not invocation or rootdir == invocation:
            return file
        return posixpath.relpath(posixpath.join(rootdir, file), invocation)

    for case in root.iter("testcase"):
        error = case.find("error")
        if error is not None and error.get("message") == "collection failure" and not case.get("classname"):
            # pytest reports a test file that failed to import as one pseudo test case named
            # after the file. It is a file-level error, never a test id.
            collection_path = rebase(
                case.get("file") or case.get("name", "").replace(".", "/") + ".py",
            )
            collection_errors.append(collection_path)
            collection_failure_text.append((collection_path, _failure_text(error)))
            continue
        file = case.get("file", "")
        nid = node_id(file, case.get("classname", ""), case.get("name", ""))
        rebased = rebase(file)
        if rebased != file and nid.startswith(file + "::"):
            nid = rebased + nid[len(file):]
        failure = case.find("failure")
        if failure is not None:
            failed.append(nid)
            testcase_failure_text.append((nid, _failure_text(failure)))
        elif error is not None:
            errors.append(nid)
            testcase_failure_text.append((nid, _failure_text(error)))
        elif case.find("skipped") is not None:
            skipped.append(nid)
        else:
            passed.append(nid)
    failure_text: dict[str, str] = {}
    recorded = 0
    for key, text in [*collection_failure_text, *testcase_failure_text]:
        if key in failure_text or recorded + len(text) > _FAILURE_TEXT_TOTAL_LIMIT:
            continue
        failure_text[key] = text
        recorded += len(text)
    return JunitSummary(
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        collection_errors=collection_errors,
        failure_text=failure_text,
    )
