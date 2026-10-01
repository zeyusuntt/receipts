"""Builds a tiny git repo with a known failing test, for executor and gate tests.

Layout of the generated repo:
    calc/__init__.py      add() correct, sub() wrong (returns a + b)
    tests/test_calc.py    test_add passes, test_sub fails, test_zero passes, test_param[a b] passes
    tests/test_flaky.py   (flaky=True only) fails on the first run, passes on the second,
                          using a counter file next to the test
"""

from __future__ import annotations

import subprocess
from pathlib import Path

CALC = '''def add(a, b):
    return a + b


def sub(a, b):
    return a + b  # bug: should be a - b
'''

TEST_CALC = '''import pytest

from calc import add, sub


def test_add():
    assert add(1, 2) == 3


def test_sub():
    assert sub(5, 3) == 2


def test_zero():
    assert add(0, 0) == 0


@pytest.mark.parametrize("label", ["a b"])
def test_param(label):
    assert label == "a b"
'''

TEST_FLAKY = '''import pathlib


def test_flaky():
    counter = pathlib.Path(__file__).with_name("flaky.count")
    n = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(n + 1))
    assert n % 2 == 1
'''


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def make_repo(root: Path, *, flaky: bool = False) -> Path:
    repo = root / "repo"
    (repo / "calc").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "calc" / "__init__.py").write_text(CALC)
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "tests" / "test_calc.py").write_text(TEST_CALC)
    (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (repo / ".gitignore").write_text("report.xml\nflaky.count\n__pycache__/\n")
    if flaky:
        (repo / "tests" / "test_flaky.py").write_text(TEST_FLAKY)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture repo")
    return repo
