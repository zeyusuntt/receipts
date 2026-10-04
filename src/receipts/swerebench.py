"""Adapt SWE-rebench V2 rows and apply its official pytest grading rule."""

from __future__ import annotations

import base64
import shlex
from pathlib import PurePosixPath
from typing import Literal

from pydantic import AliasChoices, AliasPath, BaseModel, Field

from receipts.models import Verdict
from receipts.patchscope import summarize_patch
from receipts.sandbox.protocol import ImageSource


class Instance(BaseModel):
    """The SWE-rebench fields needed to run and grade one instance."""

    instance_id: str
    repo: str
    base_commit: str
    image_name: str
    test_patch: str
    fail_to_pass: list[str] = Field(
        validation_alias=AliasChoices("fail_to_pass", "FAIL_TO_PASS"),
    )
    pass_to_pass: list[str] = Field(
        validation_alias=AliasChoices("pass_to_pass", "PASS_TO_PASS"),
    )
    test_cmd: str = Field(
        validation_alias=AliasChoices(
            "test_cmd",
            AliasPath("install_config", "test_cmd"),
        ),
    )
    problem_statement: str


class UnparseableTestPatch(ValueError):
    """The dataset's test patch names a path Receipts cannot parse, so its spec cannot be protected."""


class SweTask(BaseModel):
    source: ImageSource
    issue: str
    spec_tests: list[str]
    spec_paths: list[str]
    suite_scope: str


class OfficialJudgement(BaseModel):
    resolved: bool
    from_fail_to_pass: list[str]
    failed_from_fail_to_pass: list[str]
    failed_from_pass_to_pass: list[str]


Agreement = Literal[
    "agree_pass",
    "agree_fail",
    "gate_stricter",
    "gate_looser",
    "gate_error",
]


def _patch_path(instance: Instance) -> PurePosixPath:
    safe_id = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in instance.instance_id
    )
    return PurePosixPath("/tmp", f"receipts-{safe_id}-test.patch")


def _setup_commands(instance: Instance) -> list[str]:
    return _test_patch_setup_commands(instance.test_patch, _patch_path(instance))


def _test_patch_setup_commands(
    patch: str,
    path: PurePosixPath,
) -> list[str]:
    """Write and apply a test patch inside a sandbox image."""

    encoded = base64.b64encode(patch.encode()).decode("ascii")
    script = (
        "import base64; from pathlib import Path; "
        f"Path({str(path)!r}).write_bytes(base64.b64decode({encoded!r}))"
    )
    return [
        f"python -c {shlex.quote(script)}",
        f"git apply {shlex.quote(str(path))}",
    ]


def _test_files_from_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    files: list[str] = []
    for token in tokens:
        if token.startswith("-"):
            continue
        path = token.split("::", 1)[0]
        if not path.endswith(".py"):
            continue
        if path not in files:
            files.append(path)
    return files


def _test_files_from_patch(patch: str) -> list[str]:
    files: list[str] = []
    for changed in summarize_patch(patch).files:
        if changed.category == "test" and changed.path.endswith(".py"):
            if changed.path not in files:
                files.append(changed.path)
    return files


def _spec_paths_from_test_patch(patch: str, *, context: str) -> list[str]:
    """Return every path in a test patch, failing closed on ambiguous paths."""

    summary = summarize_patch(patch)
    if any(changed.category == "unparseable" for changed in summary.files):
        raise UnparseableTestPatch(
            f"{context}: test patch contains an unparseable path",
        )
    return [changed.path for changed in summary.files]


def to_task(instance: Instance) -> SweTask:
    """Convert one dataset row into the inputs accepted by orchestrate.fix."""

    spec_paths = _spec_paths_from_test_patch(
        instance.test_patch,
        context=instance.instance_id,
    )

    # The gate runs the instance's own pytest arguments (the suite named by test_cmd,
    # with its warning filters and options), so its runs match the official grader's.
    try:
        tokens = shlex.split(instance.test_cmd)
    except ValueError:
        tokens = instance.test_cmd.split()
    if tokens[:1] == ["pytest"]:
        suite = tokens[1:]
    elif tokens[1:3] == ["-m", "pytest"]:
        suite = tokens[3:]
    else:
        suite = _test_files_from_command(instance.test_cmd) or _test_files_from_patch(
            instance.test_patch,
        )
    return SweTask(
        source=ImageSource(
            image=instance.image_name,
            workdir="/" + instance.repo.split("/")[1],
            python="python",
            platform="linux/amd64",
            setup=_setup_commands(instance),
        ),
        issue=instance.problem_statement,
        spec_tests=list(instance.fail_to_pass),
        spec_paths=spec_paths,
        suite_scope=shlex.join(suite),
    )


# Ported from SWE-rebench-V2 lib/agent/log_parsers.py at commit c71902a8.
# Copyright 2026 SWE-rebench, used under the MIT license.
def parse_log_pytest(log: str) -> dict[str, str]:
    test_status_map: dict[str, str] = {}
    for line in log.split("\n"):
        if any(
            line.startswith(status)
            for status in ("PASSED", "FAILED", "SKIPPED", "ERROR")
        ):
            if line.startswith("FAILED"):
                line = line.replace(" - ", " ")
            test_case = line.split()
            if len(test_case) <= 1:
                continue
            test_status_map[test_case[1]] = test_case[0]
    return test_status_map


def official_command(instance: Instance) -> str:
    """Return the dataset command with pytest summary reporting enabled."""

    try:
        tokens = shlex.split(instance.test_cmd)
    except ValueError:
        tokens = instance.test_cmd.split()
    if "-rA" in tokens:
        return instance.test_cmd
    return f"{instance.test_cmd} -rA"


def official_resolved(
    instance: Instance,
    verification_log: str,
) -> OfficialJudgement:
    """Grade a verification log with the SWE-rebench V2 resolution rule."""

    outcomes = parse_log_pytest(verification_log)
    from_fail_to_pass = [
        node_id
        for node_id in instance.fail_to_pass
        if outcomes.get(node_id) == "PASSED"
    ]
    failed_from_fail_to_pass = [
        node_id
        for node_id in instance.fail_to_pass
        if outcomes.get(node_id) != "PASSED"
    ]
    failed_from_pass_to_pass = [
        node_id
        for node_id in instance.pass_to_pass
        if outcomes.get(node_id) != "PASSED"
    ]
    return OfficialJudgement(
        resolved=(
            len(from_fail_to_pass) == len(instance.fail_to_pass)
            and not failed_from_pass_to_pass
        ),
        from_fail_to_pass=from_fail_to_pass,
        failed_from_fail_to_pass=failed_from_fail_to_pass,
        failed_from_pass_to_pass=failed_from_pass_to_pass,
    )


def agreement(gate_verdict: Verdict, judgement: OfficialJudgement) -> Agreement:
    """Classify agreement between the receipt gate and official grading."""

    if gate_verdict.status == "ERROR":
        return "gate_error"
    if gate_verdict.status == "PASS":
        return "agree_pass" if judgement.resolved else "gate_looser"
    return "gate_stricter" if judgement.resolved else "agree_fail"


__all__ = [
    "Agreement",
    "Instance",
    "OfficialJudgement",
    "SweTask",
    "agreement",
    "official_command",
    "official_resolved",
    "parse_log_pytest",
    "to_task",
]
