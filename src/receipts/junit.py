"""Turn a pytest junit xml file into a JunitSummary.

pytest must be run with `-o junit_family=xunit1` so each testcase carries a
`file` attribute; the module part of `classname` is derived from it and the
remaining dotted components are the class chain.
"""

from __future__ import annotations

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
    for case in root.iter("testcase"):
        nid = node_id(case.get("file", ""), case.get("classname", ""), case.get("name", ""))
        if case.find("failure") is not None:
            failed.append(nid)
        elif case.find("error") is not None:
            errors.append(nid)
        elif case.find("skipped") is not None:
            skipped.append(nid)
        else:
            passed.append(nid)
    return JunitSummary(passed=passed, failed=failed, errors=errors, skipped=skipped)
