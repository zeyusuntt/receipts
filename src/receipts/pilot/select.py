"""Select deterministic SWE-rebench pilot candidates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from receipts.swerebench import Instance


def candidates(rows: Iterable[Mapping[str, Any]]) -> list[Instance]:
    qualified: list[Instance] = []
    for row in rows:
        install_config = row.get("install_config")
        test_cmd = row.get("test_cmd")
        if test_cmd is None and isinstance(install_config, Mapping):
            test_cmd = install_config.get("test_cmd")
        fail_to_pass = row.get("fail_to_pass", row.get("FAIL_TO_PASS"))
        if row.get("language") != "python":
            continue
        if not isinstance(test_cmd, str) or not test_cmd.startswith("pytest"):
            continue
        if not isinstance(fail_to_pass, list) or not 1 <= len(fail_to_pass) <= 3:
            continue

        safe_row = {key: row[key] for key in row if key != "patch"}
        qualified.append(Instance.model_validate(safe_row))

    qualified.sort(
        key=lambda instance: hashlib.sha256(
            instance.instance_id.encode("utf-8"),
        ).hexdigest(),
    )
    selected: list[Instance] = []
    repositories: set[str] = set()
    for instance in qualified:
        repository = instance.repo.casefold()
        if repository in repositories:
            continue
        repositories.add(repository)
        selected.append(instance)
    return selected


def write_candidates(rows_path: Path, meta_path: Path, out_path: Path) -> None:
    rows = [
        json.loads(line)
        for line in rows_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    lines = [
        f"# dataset revision {meta['revision']}",
        "# rules 1-3 of PREREGISTRATION.md",
        *(instance.instance_id for instance in candidates(rows)),
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["candidates", "write_candidates"]
