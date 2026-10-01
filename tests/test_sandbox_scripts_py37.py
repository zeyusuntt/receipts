"""Scripts that run inside a task's sandbox must work on the oldest Python the dataset
uses: SWE-rebench-V2 builds Python tasks on python_base_310 and python_base_37."""

from __future__ import annotations

import json
import shlex
import subprocess

import pytest

from receipts.orchestrate import _FREEZE_SCRIPT, _digest_command
from receipts.sandbox.protocol import PYTEST_BOOTSTRAP
from receipts.swerebench import Instance, to_task

IMAGE = "python:3.7-slim"


def _image_available() -> bool:
    try:
        probe = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _image_available(), reason=f"Docker image {IMAGE} is not available"),
]


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_a.py").write_text("def test_x():\n    assert True\n")
    (repo / "setup.cfg").write_text("[tool:pytest]\n")
    return repo


def _run(repo, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "run", "--rm", "-v", f"{repo}:/repo", "-w", "/repo", IMAGE, "sh", "-c", command],
        capture_output=True, text=True, timeout=120,
    )


def test_digest_script_runs_on_python_37(tmp_path):
    repo = _repo(tmp_path)

    result = _run(repo, _digest_command(["tests/test_a.py::test_x"]))

    assert result.returncode == 0, result.stderr
    digests = json.loads(result.stdout)
    assert "tests/test_a.py" in digests["test_digests"]
    assert "setup.cfg" in digests["pytest_config_digests"]


def test_freeze_script_runs_on_python_37(tmp_path):
    result = _run(_repo(tmp_path), f"python -c {shlex.quote(_FREEZE_SCRIPT)}")

    assert result.returncode == 0, result.stderr
    assert any(line.lower().startswith("pip==") for line in result.stdout.splitlines())


def test_test_patch_setup_command_runs_on_python_37(tmp_path):
    instance = Instance(
        instance_id="owner__repo-1", repo="owner/repo", base_commit="abc", image_name="example:1",
        test_patch="diff --git a/tests/test_a.py b/tests/test_a.py\n", fail_to_pass=["tests/test_a.py::test_x"],
        pass_to_pass=[], test_cmd="pytest tests/test_a.py", problem_statement="p",
    )
    write_patch = to_task(instance).source.setup[0]

    result = _run(_repo(tmp_path), write_patch + " && cat /tmp/receipts-owner__repo-1-test.patch")

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("diff --git a/tests/test_a.py")


def test_pytest_bootstrap_compiles_on_python_37(tmp_path):
    repo = _repo(tmp_path)
    (repo / "bootstrap.py").write_text(PYTEST_BOOTSTRAP)

    result = _run(repo, "python -c \"compile(open('bootstrap.py').read(), 'bootstrap.py', 'exec')\"")

    assert result.returncode == 0, result.stderr
