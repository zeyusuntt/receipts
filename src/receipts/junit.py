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
import xml.etree.ElementTree as ET
from pathlib import Path

from receipts.models import JunitSummary


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
            collection_errors.append(rebase(case.get("file") or case.get("name", "").replace(".", "/") + ".py"))
            continue
        file = case.get("file", "")
        nid = node_id(file, case.get("classname", ""), case.get("name", ""))
        rebased = rebase(file)
        if rebased != file and nid.startswith(file + "::"):
            nid = rebased + nid[len(file):]
        if case.find("failure") is not None:
            failed.append(nid)
        elif case.find("error") is not None:
            errors.append(nid)
        elif case.find("skipped") is not None:
            skipped.append(nid)
        else:
            passed.append(nid)
    return JunitSummary(passed=passed, failed=failed, errors=errors, skipped=skipped,
                        collection_errors=collection_errors)
