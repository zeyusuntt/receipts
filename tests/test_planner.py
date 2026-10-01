from __future__ import annotations

import importlib
import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

from receipts.llm import FakeModel
from receipts.models import Baseline, JunitSummary
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import RepoAtCommit
from receipts.sandbox.sink import MemorySink
from tests.fixtures.repo_factory import make_repo


def _planner_module() -> ModuleType:
    try:
        spec = importlib.util.find_spec("receipts.agent.planner")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "receipts.agent.planner must exist"
    return importlib.import_module("receipts.agent.planner")


def _baseline(target: str) -> Baseline:
    run = JunitSummary(
        passed=["tests/test_calc.py::test_add"],
        failed=[target],
        errors=[],
        skipped=[],
    )
    return Baseline(
        runs=[run],
        run_receipt_ids=["baseline-1"],
        collected_ids=[*run.passed, *run.failed],
        skipped_ids=[],
        protected=list(run.passed),
        unstable=[],
        target=[target],
    )


async def _fixture_executor(tmp_path: Path) -> tuple[LocalExecutor, object, MemorySink]:
    repo = make_repo(tmp_path / "source")
    sink = MemorySink()
    executor = LocalExecutor(tmp_path / "executor", sink, run_id="planner-test")
    branch = await executor.prepare(
        RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"),
    )
    return executor, branch, sink


def test_plan_has_the_public_planner_fields():
    planner = _planner_module()

    plan = planner.Plan(
        hypothesis="sub adds instead of subtracting",
        files_to_edit=["calc/__init__.py"],
        approach="Change sub and run the specification test.",
    )

    assert plan.model_dump() == {
        "hypothesis": "sub adds instead of subtracting",
        "files_to_edit": ["calc/__init__.py"],
        "approach": "Change sub and run the specification test.",
    }


async def test_make_plan_builds_context_filters_files_and_returns_read_receipts(tmp_path: Path):
    planner = _planner_module()
    executor, branch, sink = await _fixture_executor(tmp_path)
    target = "tests/test_calc.py::test_sub"
    issue = "sub(5, 3) should return 2"
    model = FakeModel(
        json_objects=[
            {
                "hypothesis": "sub uses addition",
                "files_to_edit": ["calc/__init__.py", "missing.py"],
                "approach": "Replace addition with subtraction.",
            },
        ],
    )

    plan, receipts = await planner.make_plan(
        model,
        executor,
        branch,
        issue,
        _baseline(target),
        [target],
    )

    assert plan.files_to_edit == ["calc/__init__.py"]
    assert "missing.py" in plan.approach
    assert len(model.requests) == 1
    request = model.requests[0]
    assert request["kind"] == "complete_json"
    assert request["schema"] is planner.Plan
    assert issue in request["user"]
    assert target in request["user"]
    assert "def test_sub():" in request["user"]
    assert "def sub(a, b):" in request["user"]
    system = request["system"].lower()
    assert "tests named" in system and "specification" in system
    assert "read-only" in system
    assert "smallest change" in system
    assert "only files that exist" in system
    assert "tracked-files list" not in system
    assert len(receipts) == 1
    assert receipts[0].cmd == "git ls-files -z"
    assert receipts[0].branch_id == branch.id
    assert receipts == sink.receipts[1:]


async def test_make_plan_caps_tree_import_count_and_file_bytes(tmp_path: Path):
    planner = _planner_module()
    repo = make_repo(tmp_path / "source")
    imported = {
        "module_one.py": "ONE_START\n" + ("a" * 12_000) + "ONE_AFTER_LIMIT\n",
        "module_two.py": "TWO_SOURCE_MARKER = 2\n",
        "module_three.py": "THREE_SOURCE_MARKER = 3\n",
        "module_four.py": "FOUR_SOURCE_MARKER = 4\n",
        "module_five.py": "FIVE_SOURCE_MARKER = 5\n",
        "module_six.py": "SIX_SOURCE_MARKER = 6\n",
    }
    for name, content in imported.items():
        (repo / name).write_text(content)
    (repo / "tests" / "test_imports.py").write_text(
        "import module_one\n"
        "import module_two\n"
        "import module_three\n"
        "import module_four\n"
        "import module_five\n"
        "import module_six\n\n"
        "def test_imports():\n"
        "    assert True\n",
    )
    for index in range(390):
        (repo / f"root_keep_{index:03}.txt").write_text(str(index))
    deep = repo / "deep" / "level" / "path" / "drop_me.py"
    deep.parent.mkdir(parents=True)
    deep.write_text("DEEPEST_PATH_MARKER = True\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "planner fixture"],
        cwd=repo,
        check=True,
    )

    sink = MemorySink()
    executor = LocalExecutor(tmp_path / "executor", sink, run_id="planner-limits")
    branch = await executor.prepare(
        RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"),
    )
    target = "tests/test_imports.py::test_imports"
    model = FakeModel(
        json_objects=[
            {
                "hypothesis": "one imported module is wrong",
                "files_to_edit": ["module_one.py"],
                "approach": "Inspect the imported modules.",
            },
        ],
    )

    await planner.make_plan(
        model,
        executor,
        branch,
        "Find the imported-module bug",
        _baseline(target),
        [target],
    )

    prompt = model.requests[0]["user"]
    assert "root_keep_389.txt" in prompt
    assert "deep/level/path/drop_me.py" not in prompt
    assert "ONE_START" in prompt
    assert "ONE_AFTER_LIMIT" not in prompt
    assert "TWO_SOURCE_MARKER" in prompt
    assert "THREE_SOURCE_MARKER" in prompt
    assert "FOUR_SOURCE_MARKER" in prompt
    assert "FIVE_SOURCE_MARKER" in prompt
    assert "SIX_SOURCE_MARKER" not in prompt


async def test_make_plan_handles_git_quoted_unicode_paths(tmp_path: Path):
    planner = _planner_module()
    repo = make_repo(tmp_path / "source")
    unicode_source = repo / "calc" / "μhelper.py"
    unicode_source.write_text("UNICODE_SOURCE_MARKER = 7\n")
    unicode_test = repo / "tests" / "test_unicode.py"
    unicode_test.write_text(
        "from calc.μhelper import UNICODE_SOURCE_MARKER\n\n"
        "def test_unicode():\n"
        "    assert UNICODE_SOURCE_MARKER == 7\n",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "unicode planner fixture"],
        cwd=repo,
        check=True,
    )
    sink = MemorySink()
    executor = LocalExecutor(tmp_path / "executor", sink, run_id="planner-unicode")
    branch = await executor.prepare(
        RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"),
    )
    target = "tests/test_unicode.py::test_unicode"
    model = FakeModel(
        json_objects=[
            {
                "hypothesis": "the Unicode helper is wrong",
                "files_to_edit": ["calc/μhelper.py"],
                "approach": "Fix the helper.",
            },
        ],
    )

    plan, _ = await planner.make_plan(
        model,
        executor,
        branch,
        "Fix the Unicode helper",
        _baseline(target),
        [target],
    )

    assert plan.files_to_edit == ["calc/μhelper.py"]
    assert "UNICODE_SOURCE_MARKER" in model.requests[0]["user"]


async def test_make_plan_keeps_imports_before_a_truncated_expression(tmp_path: Path):
    planner = _planner_module()
    repo = make_repo(tmp_path / "source")
    long_test = repo / "tests" / "test_long.py"
    long_test.write_text(
        "from calc import sub\n\n"
        "PAYLOAD = '''" + ("x" * 13_000) + "'''\n\n"
        "def test_long():\n"
        "    assert sub(5, 3) == 2\n",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "long test planner fixture"],
        cwd=repo,
        check=True,
    )
    sink = MemorySink()
    executor = LocalExecutor(tmp_path / "executor", sink, run_id="planner-long-test")
    branch = await executor.prepare(
        RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"),
    )
    target = "tests/test_long.py::test_long"
    model = FakeModel(
        json_objects=[
            {
                "hypothesis": "sub uses addition",
                "files_to_edit": ["calc/__init__.py"],
                "approach": "Fix sub.",
            },
        ],
    )

    await planner.make_plan(
        model,
        executor,
        branch,
        "Fix the long specification test",
        _baseline(target),
        [target],
    )

    assert "def sub(a, b):" in model.requests[0]["user"]
