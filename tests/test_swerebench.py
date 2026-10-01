import json
from pathlib import Path

import pytest

from receipts.models import Verdict
from receipts.swerebench import (
    Instance,
    OfficialJudgement,
    agreement,
    official_command,
    official_resolved,
    parse_log_pytest,
    to_task,
)


DATA = Path(__file__).parent / "data" / "swerebench_docformatter_254.json"


def _docformatter() -> Instance:
    return Instance.model_validate(json.loads(DATA.read_text(encoding="utf-8")))


def _verdict(status: str) -> Verdict:
    return Verdict(
        branch_id="agent1",
        status=status,
        predicates=[],
        claim_audit="no_claim",
        claim_evidence="not relevant to official grading",
    )


def _judgement(resolved: bool) -> OfficialJudgement:
    return OfficialJudgement(
        resolved=resolved,
        from_fail_to_pass=["tests/test_fix.py::test_target"] if resolved else [],
        failed_from_fail_to_pass=[] if resolved else ["tests/test_fix.py::test_target"],
        failed_from_pass_to_pass=[],
    )


def _passing_log(instance: Instance) -> str:
    return "\n".join(
        f"PASSED {node_id}"
        for node_id in [*instance.fail_to_pass, *instance.pass_to_pass]
    )


def test_parse_log_pytest_keeps_upstream_summary_behavior():
    log = """\
============================= test session starts ==============================
PASSED tests/test_api.py::test_param[value-1]
PASSED tests/test_api.py::test_space[value with spaces]
FAILED tests/test_api.py::test_failed - AssertionError: expected true
SKIPPED tests/test_api.py::test_skipped
XFAIL tests/test_api.py::test_expected_failure - known issue
ERROR tests/test_api.py::test_error - RuntimeError: setup failed
=========================== short test summary info ============================
"""

    assert parse_log_pytest(log) == {
        "tests/test_api.py::test_param[value-1]": "PASSED",
        "tests/test_api.py::test_space[value": "PASSED",
        "tests/test_api.py::test_failed": "FAILED",
        "tests/test_api.py::test_skipped": "SKIPPED",
        "tests/test_api.py::test_error": "ERROR",
    }


def test_docformatter_row_converts_to_expected_task():
    instance = _docformatter()

    task = to_task(instance)

    assert instance.test_cmd == (
        "pytest --no-header -rA --tb=line --color=no -p no:cacheprovider "
        "-W ignore::DeprecationWarning tests/formatter/test_format_sphinx.py"
    )
    assert task.source.image == "docker.io/swerebenchv2/pycqa-docformatter:254-5c9744e"
    assert task.source.workdir == "/docformatter"
    assert task.source.python == "python"
    assert task.source.platform == "linux/amd64"
    assert len(task.source.setup) == 2
    assert "/tmp/receipts-pycqa__docformatter-254-test.patch" in task.source.setup[0]
    assert task.source.setup[1] == (
        "git apply /tmp/receipts-pycqa__docformatter-254-test.patch"
    )
    assert task.issue == instance.problem_statement
    assert task.spec_tests == [
        "tests/formatter/test_format_sphinx.py::TestFormatWrapSphinx::"
        "test_format_docstring_sphinx_style_recognize_yield[args0]",
    ]
    assert task.suite_scope == "tests/formatter/test_format_sphinx.py"


def test_to_task_uses_test_files_from_patch_when_command_names_none():
    instance = Instance(
        instance_id="owner__repo-1",
        repo="owner/repo",
        base_commit="abc123",
        image_name="example/repo:latest",
        test_patch=(
            "diff --git a/tests/test_one.py b/tests/test_one.py\n"
            "--- a/tests/test_one.py\n"
            "+++ b/tests/test_one.py\n"
            "diff --git a/src/example.py b/src/example.py\n"
            "--- a/src/example.py\n"
            "+++ b/src/example.py\n"
        ),
        fail_to_pass=["tests/test_one.py::test_fix"],
        pass_to_pass=[],
        test_cmd="pytest -q",
        problem_statement="Fix it",
    )

    assert to_task(instance).suite_scope == "tests/test_one.py"


def test_official_command_preserves_docformatter_command_with_report_flag():
    instance = _docformatter()

    assert official_command(instance) == instance.test_cmd


def test_official_command_adds_report_flag_when_missing():
    instance = _docformatter().model_copy(update={"test_cmd": "pytest tests"})

    assert official_command(instance) == "pytest tests -rA"


def test_official_resolved_when_every_required_test_passes():
    instance = _docformatter()

    judgement = official_resolved(instance, _passing_log(instance))

    assert judgement.resolved is True
    assert judgement.from_fail_to_pass == instance.fail_to_pass
    assert judgement.failed_from_fail_to_pass == []
    assert judgement.failed_from_pass_to_pass == []


def test_official_not_resolved_when_fail_to_pass_test_fails():
    instance = _docformatter()
    log = _passing_log(instance).replace(
        f"PASSED {instance.fail_to_pass[0]}",
        f"FAILED {instance.fail_to_pass[0]} - AssertionError: still broken",
    )

    judgement = official_resolved(instance, log)

    assert judgement.resolved is False
    assert judgement.from_fail_to_pass == []
    assert judgement.failed_from_fail_to_pass == instance.fail_to_pass
    assert judgement.failed_from_pass_to_pass == []


def test_official_not_resolved_when_pass_to_pass_test_is_missing():
    instance = _docformatter()
    missing = instance.pass_to_pass[-1]
    log = "\n".join(
        f"PASSED {node_id}"
        for node_id in [*instance.fail_to_pass, *instance.pass_to_pass[:-1]]
    )

    judgement = official_resolved(instance, log)

    assert judgement.resolved is False
    assert judgement.failed_from_fail_to_pass == []
    assert judgement.failed_from_pass_to_pass == [missing]


def test_official_not_resolved_when_fail_to_pass_test_is_xfail():
    instance = _docformatter()
    log = "\n".join(
        [
            f"XFAIL {instance.fail_to_pass[0]} - known issue",
            *(f"PASSED {node_id}" for node_id in instance.pass_to_pass),
        ],
    )

    judgement = official_resolved(instance, log)

    assert judgement.resolved is False
    assert judgement.failed_from_fail_to_pass == instance.fail_to_pass
    assert judgement.failed_from_pass_to_pass == []


@pytest.mark.parametrize(
    ("status", "resolved", "expected"),
    [
        ("PASS", True, "agree_pass"),
        ("REJECTED", False, "agree_fail"),
        ("REJECTED", True, "gate_stricter"),
        ("PASS", False, "gate_looser"),
        ("ERROR", True, "gate_error"),
        ("ERROR", False, "gate_error"),
    ],
)
def test_agreement_covers_gate_and_official_outcomes(status, resolved, expected):
    assert agreement(_verdict(status), _judgement(resolved)) == expected
