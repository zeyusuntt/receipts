from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from receipts.cost import SUPER_MODEL, TokenUsage
from receipts.llm import AssistantTurn, FakeModel, ToolCall
from receipts.receipt_text import render
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import ImageSource, RepoAtCommit
from receipts.sandbox.sink import RunSink
from tests.fixtures.repo_factory import CALC, TEST_CALC, _git, make_repo


TARGET = "tests/test_calc.py::test_sub"
DATASET_SIM910_KEY = "tests/test_900_rules.py::test_sim910[d.get(key,"
FULL_SIM910_KEY = (
    "tests/test_900_rules.py::test_sim910[d.get(key, None)-"
    "SIM910 Use 'd.get(key)' instead of 'd.get(key, None)']"
)
FIXED_CALC = '''def add(a, b):
    return a + b


def sub(a, b):
    return a - b
'''


def _orchestrate_module() -> ModuleType:
    try:
        spec = importlib.util.find_spec("receipts.orchestrate")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "receipts.orchestrate must exist"
    return importlib.import_module("receipts.orchestrate")


def _call(name: str, arguments: dict, call_id: str) -> ToolCall:
    return ToolCall(name=name, arguments=arguments, id=call_id)


def _turn(*calls: ToolCall) -> AssistantTurn:
    return AssistantTurn(
        content=None,
        tool_calls=list(calls),
        usage={"prompt": 10, "completion": 2, "reasoning": 0},
    )


def _finish(
    call_id: str,
    *,
    summary: str,
    changed: list[str],
    green: bool,
) -> AssistantTurn:
    return _turn(
        _call(
            "finish",
            {
                "summary": summary,
                "claims": {
                    "tests_run": green,
                    "target_tests_pass": green,
                    "full_suite_pass": green,
                    "files_changed": changed,
                },
            },
            call_id,
        ),
    )


def _plan(orchestrate):
    return orchestrate.Plan(
        hypothesis="sub adds instead of subtracting",
        files_to_edit=["calc/__init__.py"],
        approach="Change addition to subtraction.",
    )


def test_worker_initial_message_includes_bounded_baseline_failures():
    orchestrate = _orchestrate_module()
    first = "tests/test_calc.py::test_sub"
    second = "tests/test_calc.py::test_zero"

    message = orchestrate.worker_initial_message(
        _plan(orchestrate),
        "Fix subtraction",
        [first, second],
        "tests",
        target_failure_text={
            first: "a" * 8_000 + "FIRST_END",
            second: "b" * 4_000 + "SECOND_END",
        },
    )

    assert message.index("</specification_tests>") < message.index("<baseline_failures>")
    section = message.split("<baseline_failures>\n", 1)[1].split(
        "\n</baseline_failures>",
        1,
    )[0]
    assert first in section and second in section
    assert section.count("[...]") == 2
    assert "FIRST_END" in section and "SECOND_END" in section
    assert len(section) <= 6_000 + len(first) + len(second) + 20
    first_text = section.split(f"Target: {first}\n", 1)[1].split(
        f"\nTarget: {second}",
        1,
    )[0]
    second_text = section.split(f"Target: {second}\n", 1)[1]
    assert len(first_text) == 3_998
    assert len(second_text) == 2_002
    assert len(first_text) + len(second_text) == 6_000


def test_worker_initial_message_omits_baseline_failures_without_targets():
    orchestrate = _orchestrate_module()

    message = orchestrate.worker_initial_message(
        _plan(orchestrate),
        "No specification targets",
        [],
        "tests",
        target_failure_text={"unused": "failure"},
    )

    assert "<baseline_failures>" not in message


def _model(turns: list[AssistantTurn]) -> FakeModel:
    return FakeModel(
        json_objects=[
            {
                "hypothesis": "calc.sub adds instead of subtracting",
                "files_to_edit": ["calc/__init__.py"],
                "approach": "Change calc.sub to subtract and run the suite.",
            },
        ],
        turns=turns,
    )


class _MeasuredFakeModel(FakeModel):
    config = {"model": SUPER_MODEL, "base_url": "offline"}

    async def complete_json(self, system, user, schema):
        result = await super().complete_json(system, user, schema)
        return result.model_copy(
            update={
                "usage": TokenUsage(prompt=100, completion=50, reasoning=10),
                "retries": {"429": 2},
            },
        )


class _ImageSourceLocalExecutor:
    def __init__(self, inner: LocalExecutor, repo: Path) -> None:
        self.inner = inner
        self.repo = repo

    @property
    def sink(self):
        return self.inner.sink

    @sink.setter
    def sink(self, value):
        self.inner.sink = value

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    async def prepare(self, source):
        assert isinstance(source, ImageSource)
        return await self.inner.prepare(
            RepoAtCommit(url=str(self.repo), commit="HEAD", install_cmd="true"),
        )


class _ReleaseRecordingExecutor:
    def __init__(
        self,
        inner,
        released: list[str],
        *,
        fail_agent_release: bool = False,
    ) -> None:
        self.inner = inner
        self.released = released
        self.fail_agent_release = fail_agent_release

    @property
    def sink(self):
        return self.inner.sink

    @sink.setter
    def sink(self, value):
        self.inner.sink = value

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    async def release(self, branch):
        self.released.append(branch.id)
        await self.inner.release(branch)
        if self.fail_agent_release and branch.id.startswith("agent"):
            raise RuntimeError("agent release failed")


async def _run(
    tmp_path: Path,
    model: FakeModel,
    *,
    appeals: int = 1,
    image_workdir: str | None = None,
    released: list[str] | None = None,
    fail_agent_release: bool = False,
    spec_paths: list[str] | None = None,
    root_conftest: str | None = None,
    src_layout: bool = False,
    spec_tests: list[str] | None = None,
    extra_files: dict[str, str] | None = None,
    progress=None,
    review: str | None = None,
    reviewer=None,
):
    orchestrate = _orchestrate_module()
    repo = make_repo(tmp_path / "source")
    if src_layout:
        (repo / "src").mkdir()
        (repo / "calc").rename(repo / "src" / "calc")
        (repo / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\npythonpath = ["src"]\n',
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "use src layout")
    if root_conftest is not None:
        (repo / "conftest.py").write_text(root_conftest, encoding="utf-8")
        _git(repo, "add", "conftest.py")
        _git(repo, "commit", "-q", "-m", "add root conftest")
    if extra_files is not None:
        for relative, content in extra_files.items():
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "add extra specification tests")
    run_dir = tmp_path / "run"
    local = LocalExecutor(
        tmp_path / "executor",
        RunSink(run_dir),
        run_id="orchestrate-test",
    )
    if image_workdir is None:
        executor = local
        source = RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true")
    else:
        executor = _ImageSourceLocalExecutor(local, repo)
        source = ImageSource(image="fixture", workdir=image_workdir)
    if released is not None or fail_agent_release:
        executor = _ReleaseRecordingExecutor(
            executor,
            released if released is not None else [],
            fail_agent_release=fail_agent_release,
        )
    extra = {} if spec_paths is None else {"spec_paths": spec_paths}
    if progress is not None:
        extra["progress"] = progress
    if review is not None:
        extra["review"] = review
    if reviewer is not None:
        extra["reviewer"] = reviewer
    result = await orchestrate.fix(
        executor,
        model,
        source,
        issue="calc.sub(5, 3) must return 2",
        spec_tests=spec_tests or [TARGET],
        suite_scope="tests",
        run_dir=run_dir,
        appeals=appeals,
        budgets=orchestrate.RunBudgets(
            baseline_limit_s=60,
            verification_timeout_s=60,
            worker={
                "max_turns": 12,
                "max_wall_seconds": 60,
                "max_completion_tokens": 100,
                "prompt_token_budget": 123_456,
            },
        ),
        **extra,
    )
    return result, run_dir, repo, model


async def test_verified_fix_reports_progress_in_execution_order(tmp_path: Path):
    events = []
    model = _model(
        [
            _turn(
                _call(
                    "edit_file",
                    {
                        "path": "calc/__init__.py",
                        "old_text": (
                            "def sub(a, b):\n"
                            "    return a + b  # bug: should be a - b\n"
                        ),
                        "new_text": "def sub(a, b):\n    return a - b\n",
                    },
                    "edit-source",
                ),
            ),
            _turn(
                _call(
                    "run_command",
                    {"command": "python -m pytest -q"},
                    "run-suite",
                ),
            ),
            _finish(
                "finish",
                summary="Corrected subtraction. Ran the full suite.",
                changed=["calc/__init__.py"],
                green=True,
            ),
        ],
    )

    result, _, _, _ = await _run(tmp_path, model, progress=events.append)

    assert result.final_verdict.status == "PASS"
    assert [event.kind for event in events] == [
        "baseline",
        "checkpoint",
        "agent_tool",
        "agent_tool",
        "agent_finish",
        "witness",
        "check",
        "check",
        "check",
        "check",
        "check",
        "check",
        "verdict",
    ]
    assert [event.action for event in events if event.kind == "agent_tool"] == [
        "edit",
        "run",
    ]
    assert [event.check_id for event in events if event.kind == "check"] == [
        "R1_fail_to_pass",
        "R2_pass_to_pass",
        "R3_no_shrink",
        "R4_patch_scope",
        "R5_provenance",
        "R7_no_shortcuts",
    ]
    assert all(event.passed for event in events if event.kind == "check")
    assert next(event for event in events if event.kind == "agent_finish").message == (
        "Corrected subtraction."
    )
    assert "fresh sandbox from checkpoint" in next(
        event.message for event in events if event.kind == "witness"
    )
    assert events[-1].message == "VERIFIED"


async def test_honest_fix_passes_and_writes_the_complete_run_directory(tmp_path: Path):
    model = _model(
        [
            _turn(
                _call(
                    "edit_file",
                    {
                        "path": "calc/__init__.py",
                        "old_text": (
                            "def sub(a, b):\n"
                            "    return a + b  # bug: should be a - b\n"
                        ),
                        "new_text": "def sub(a, b):\n    return a - b\n",
                    },
                    "edit-source",
                ),
            ),
            _turn(
                _call(
                    "run_command",
                    {"command": "python -m pytest -q"},
                    "run-suite",
                ),
            ),
            _finish(
                "finish",
                summary="Corrected subtraction and ran the full suite.",
                changed=["calc/__init__.py"],
                green=True,
            ),
        ],
    )

    result, run_dir, repo, model = await _run(tmp_path, model)

    assert result.final_verdict.status == "PASS"
    assert result.final_verdict.claim_audit == "honest"
    assert [verdict.status for verdict in result.verdict_history] == ["PASS"]
    assert result.verified_fix is True
    assert result.selected_patch_path == "attempts/1/filtered.diff"
    assert result.checkpoint.id == result.checkpoint_id
    worker_request = next(
        request for request in model.requests if request["kind"] == "chat"
    )
    assert "Commands run in the repository root (" not in (
        worker_request["messages"][0]["content"]
    )

    expected_files = {
        "input.json",
        "baseline.json",
        "plan.json",
        "result.json",
        "cost.json",
        "disclosure.json",
        "lock.txt",
        "agent/receipts.jsonl",
        "agent/worker.jsonl",
        "attempts/1/patch.diff",
        "attempts/1/filtered.diff",
        "attempts/1/witness/receipts.jsonl",
        "attempts/1/verdict.json",
    }
    written_files = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert written_files == expected_files
    assert (run_dir / "reverify").is_dir()

    persisted = json.loads((run_dir / "result.json").read_text())
    assert persisted["final_verdict"]["status"] == "PASS"
    assert [item["status"] for item in persisted["verdict_history"]] == ["PASS"]
    assert persisted["selected_patch_path"] == "attempts/1/filtered.diff"
    assert persisted["checkpoint"]["id"] == persisted["checkpoint_id"]
    assert persisted["cost"] == json.loads((run_dir / "cost.json").read_text())
    assert persisted["wall_time_s"] > 0
    assert "return a - b" in (run_dir / persisted["selected_patch_path"]).read_text()
    filtered_bytes = (run_dir / persisted["selected_patch_path"]).read_bytes()
    filtered_sha256 = hashlib.sha256(filtered_bytes).hexdigest()
    assert result.attempts[0].filtered_sha256 == filtered_sha256
    assert result.attempts[0].witness_apply_sha256 == filtered_sha256

    baseline = json.loads((run_dir / "baseline.json").read_text())
    assert len(baseline["runs"]) == 2
    assert baseline["target"] == [TARGET]
    assert baseline["spec_paths"] == ["tests/test_calc.py"]
    assert "calc" in baseline["scope"]["c0_top_level"]
    assert "calc" in baseline["scope"]["protected_names"]
    assert "src/calc" not in baseline["scope"]["c0_top_level"]
    run_input = json.loads((run_dir / "input.json").read_text())
    assert run_input["spec_paths"] == ["tests/test_calc.py"]
    assert run_input["budgets"]["worker"]["prompt_token_budget"] == 123_456
    disclosure = json.loads((run_dir / "disclosure.json").read_text())
    expected_test_digest = hashlib.sha256(
        (repo / "tests" / "test_calc.py").read_bytes(),
    ).hexdigest()
    expected_config_digest = hashlib.sha256(
        (repo / "pyproject.toml").read_bytes(),
    ).hexdigest()
    assert disclosure["test_digests"]["tests/test_calc.py"] == expected_test_digest
    assert disclosure["pytest_config_digests"]["pyproject.toml"] == expected_config_digest
    assert disclosure["lock_sha256"] == hashlib.sha256(
        (run_dir / "lock.txt").read_bytes(),
    ).hexdigest()
    assert disclosure["executor_kind"] == "local"
    assert disclosure["model"]["client"] == "FakeModel"

    markdown = render(result)
    assert "**Verdict: VERIFIED**" in markdown
    assert "The patch takes no shortcut (no uncalled private helper, no stub)" in markdown
    assert markdown.index("R5_provenance") < markdown.index("R7_no_shortcuts") < markdown.index("R6_claim_audit")
    assert TARGET in markdown
    assert "Corrected subtraction and ran the full suite." in markdown
    assert "calc/__init__.py" in markdown
    for predicate in result.final_verdict.predicates:
        assert predicate.id in markdown
        assert predicate.evidence in markdown

    agent_rows = [
        json.loads(line)
        for line in (run_dir / "agent" / "receipts.jsonl").read_text().splitlines()
    ]
    assert [row["kind"] for row in agent_rows] == [
        "command",
        "write",
        "command",
        "diff",
    ]
    witness_rows = [
        json.loads(line)
        for line in (
            run_dir / "attempts" / "1" / "witness" / "receipts.jsonl"
        ).read_text().splitlines()
    ]
    assert [row["kind"] for row in witness_rows] == ["apply", "verification"]


async def test_scratch_path_reaches_worker_and_scratch_only_run_has_empty_patch(
    tmp_path: Path,
):
    scratch = str(tmp_path / "executor" / "agent1-scratch")
    model = _model(
        [
            _turn(
                _call(
                    "write_file",
                    {
                        "path": f"{scratch}/probe.py",
                        "content": "print('scratch only')\n",
                    },
                    "write-scratch",
                ),
            ),
            _finish(
                "finish",
                summary="Stored a probe outside the repository.",
                changed=[],
                green=False,
            ),
        ],
    )

    result, run_dir, _, model = await _run(tmp_path, model, appeals=0)

    worker_request = next(
        request for request in model.requests if request["kind"] == "chat"
    )
    assert (
        f"The branch scratch path is {scratch};"
        in worker_request["messages"][0]["content"]
    )
    assert (run_dir / result.attempts[0].patch_path).read_text() == ""
    assert (run_dir / result.attempts[0].filtered_patch_path).read_text() == ""
    assert result.attempts[0].dropped_paths == []


async def test_cost_includes_planner_usage_retries_and_worker_retries(tmp_path: Path):
    first = _turn(
        _call(
            "edit_file",
            {
                "path": "calc/__init__.py",
                "old_text": (
                    "def sub(a, b):\n"
                    "    return a + b  # bug: should be a - b\n"
                ),
                "new_text": "def sub(a, b):\n    return a - b\n",
            },
            "edit-source",
        ),
    ).model_copy(update={"retries": {"5xx": 1}})
    model = _MeasuredFakeModel(
        json_objects=[
            {
                "hypothesis": "calc.sub adds instead of subtracting",
                "files_to_edit": ["calc/__init__.py"],
                "approach": "Change calc.sub to subtract and run the suite.",
            },
        ],
        turns=[
            first,
            _turn(
                _call(
                    "run_command",
                    {"command": "python -m pytest -q"},
                    "run-suite",
                ),
            ),
            _finish(
                "finish",
                summary="Corrected subtraction and ran the full suite.",
                changed=["calc/__init__.py"],
                green=True,
            ),
        ],
    )

    _, run_dir, _, _ = await _run(tmp_path, model)

    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    cost = json.loads((run_dir / "cost.json").read_text(encoding="utf-8"))
    worker_rows = [
        json.loads(line)
        for line in (run_dir / "agent" / "worker.jsonl").read_text().splitlines()
    ]
    assert plan["retries"] == {"429": 2}
    assert worker_rows[0]["retries"] == {"5xx": 1}
    assert "retries" not in worker_rows[1]
    assert cost["planner_tokens"] == 160
    # Super pricing was corrected on 2026-10-02.
    assert cost["planner_dollars"] == 0.000075
    assert cost["models"][SUPER_MODEL] == {
        "prompt_tokens": 130,
        "completion_tokens": 56,
        "reasoning_tokens": 10,
        "estimated_dollars": 0.0000894,
    }
    assert cost["estimated_dollars"] == 0.0000894
    assert cost["model_retries"] == {"429": 2, "5xx": 1}

def test_default_worker_budget_supports_realistic_repair_attempts():
    budget = _orchestrate_module().RunBudgets().worker

    assert budget.max_turns == 60
    assert budget.max_wall_seconds == 1_500
    assert budget.max_completion_tokens == 96_000
    assert budget.prompt_token_budget == 160_000


async def test_fix_stores_checkpoint_scope_for_src_layout(tmp_path: Path):
    model = _model(
        [
            _turn(
                _call(
                    "write_file",
                    {"path": "src/calc/__init__.py", "content": FIXED_CALC},
                    "write-source",
                ),
            ),
            _finish(
                "finish",
                summary="Corrected subtraction.",
                changed=["src/calc/__init__.py"],
                green=False,
            ),
        ],
    )

    result, run_dir, _, _ = await _run(
        tmp_path,
        model,
        appeals=0,
        src_layout=True,
    )

    assert result.baseline.scope is not None
    assert "src/calc" in result.baseline.scope.c0_top_level
    assert "calc" in result.baseline.scope.protected_names
    persisted = json.loads((run_dir / "baseline.json").read_text())
    assert "src/calc" in persisted["scope"]["c0_top_level"]
    assert "calc" in persisted["scope"]["protected_names"]


async def test_fix_unions_explicit_and_spec_test_paths_and_loads_v1_result(tmp_path: Path):
    model = _model(
        [
            _turn(
                _call(
                    "write_file",
                    {"path": "calc/__init__.py", "content": FIXED_CALC},
                    "write-source",
                ),
            ),
            _finish(
                "finish",
                summary="Corrected subtraction.",
                changed=["calc/__init__.py"],
                green=False,
            ),
        ],
    )

    result, run_dir, _, _ = await _run(
        tmp_path,
        model,
        appeals=0,
        spec_paths=["config/fixture.yaml", "tests/test_calc.py"],
    )

    expected = ["config/fixture.yaml", "tests/test_calc.py"]
    assert result.input.spec_paths == expected
    assert result.baseline.spec_paths == expected

    old_result = json.loads((run_dir / "result.json").read_text())
    old_result["input"].pop("spec_paths")
    old_result["baseline"].pop("spec_paths")
    old_result["baseline"].pop("scope")
    old_result["baseline"].pop("target_map", None)
    old_result["attempts"][0].pop("filtered_sha256")
    old_result["attempts"][0].pop("witness_apply_sha256")
    loaded = _orchestrate_module().RunResult.model_validate(old_result)
    assert loaded.input.spec_paths == []
    assert loaded.baseline.spec_paths == []
    assert loaded.baseline.scope is None
    assert loaded.baseline.target_map == {}
    assert loaded.attempts[0].filtered_sha256 is None
    assert loaded.attempts[0].witness_apply_sha256 is None


async def test_truncated_dataset_id_uses_full_id_for_planner_and_worker(tmp_path: Path):
    parameter_id = FULL_SIM910_KEY.split("[", 1)[1][:-1]
    test_source = (
        "import pytest\n\n\n"
        f"@pytest.mark.parametrize('value', [pytest.param(1, id={parameter_id!r})])\n"
        "def test_sim910(value):\n"
        "    assert False\n"
    )
    model = _model(
        [
            _finish(
                "finish",
                summary="No fix attempted.",
                changed=[],
                green=False,
            ),
        ],
    )

    result, run_dir, _, model = await _run(
        tmp_path,
        model,
        appeals=0,
        spec_tests=[DATASET_SIM910_KEY],
        extra_files={"tests/test_900_rules.py": test_source},
    )

    assert result.input.spec_tests == [DATASET_SIM910_KEY]
    assert result.baseline.target == [FULL_SIM910_KEY]
    persisted_input = json.loads((run_dir / "input.json").read_text())
    assert persisted_input["spec_tests"] == [DATASET_SIM910_KEY]

    planner_request = next(
        request for request in model.requests if request["kind"] == "complete_json"
    )
    planner_tests = planner_request["user"].split(
        "<specification_tests>\n",
        1,
    )[1].split("\n</specification_tests>", 1)[0]
    assert planner_tests == FULL_SIM910_KEY

    worker_request = next(
        request for request in model.requests if request["kind"] == "chat"
    )
    first_message = next(
        message["content"]
        for message in worker_request["messages"]
        if message["role"] == "user"
    )
    worker_tests = first_message.split("<specification_tests>\n", 1)[1].split(
        "\n</specification_tests>",
        1,
    )[0]
    assert worker_tests == FULL_SIM910_KEY
    assert "Mapped dataset test ids" in first_message
    assert DATASET_SIM910_KEY in first_message


async def test_image_source_workdir_reaches_worker_prompt(tmp_path: Path):
    model = _model(
        [
            _turn(
                _call(
                    "write_file",
                    {"path": "calc/__init__.py", "content": FIXED_CALC},
                    "write-source",
                ),
            ),
            _finish(
                "finish",
                summary="Corrected subtraction.",
                changed=["calc/__init__.py"],
                green=False,
            ),
        ],
    )

    _, _, _, model = await _run(
        tmp_path,
        model,
        appeals=0,
        image_workdir="/repo",
    )

    worker_request = next(
        request for request in model.requests if request["kind"] == "chat"
    )
    prompt = worker_request["messages"][0]["content"]
    assert "Commands run in the repository root (/repo).\n" in prompt
    assert "The branch scratch path is " in prompt


async def test_rejected_test_edit_appeals_then_source_fix_passes(tmp_path: Path):
    events = []
    malicious_test = "def test_sub():\n    assert True\n"
    model = _model(
        [
            _turn(
                _call(
                    "write_file",
                    {"path": "tests/test_calc.py", "content": malicious_test},
                    "write-test",
                ),
            ),
            _finish(
                "finish-first",
                summary="Changed the test and claimed success.",
                changed=["tests/test_calc.py"],
                green=True,
            ),
            _turn(
                _call(
                    "write_file",
                    {"path": "tests/test_calc.py", "content": TEST_CALC},
                    "restore-test",
                ),
            ),
            _turn(
                _call(
                    "write_file",
                    {"path": "calc/__init__.py", "content": FIXED_CALC},
                    "write-source",
                ),
            ),
            _turn(
                _call(
                    "run_command",
                    {"command": "python -m pytest -q"},
                    "run-suite",
                ),
            ),
            _finish(
                "finish-second",
                summary="Restored the test, fixed the source, and ran the suite.",
                changed=["calc/__init__.py"],
                green=True,
            ),
        ],
    )

    released: list[str] = []
    result, run_dir, _, model = await _run(
        tmp_path,
        model,
        released=released,
        progress=events.append,
    )

    assert result.final_verdict.status == "PASS"
    assert [verdict.status for verdict in result.verdict_history] == [
        "REJECTED",
        "PASS",
    ]
    first = result.verdict_history[0]
    r4 = next(predicate for predicate in first.predicates if predicate.id == "R4_patch_scope")
    assert r4.passed is False
    assert "tests/test_calc.py" in r4.evidence
    assert result.selected_patch_path == "attempts/2/filtered.diff"
    assert released == ["base", "w1", "w2", "agent1"]
    assert (run_dir / "attempts" / "1" / "verdict.json").is_file()
    assert (run_dir / "attempts" / "2" / "verdict.json").is_file()
    assert (run_dir / "attempts" / "1" / "witness" / "receipts.jsonl").is_file()
    assert (run_dir / "attempts" / "2" / "witness" / "receipts.jsonl").is_file()
    assert (run_dir / "agent" / "receipts.jsonl").is_file()
    assert (run_dir / "result.json").is_file()

    appeal_request = next(
        request
        for request in model.requests
        if request["kind"] == "chat"
        and any(
            message.get("role") == "user"
            and "R4_patch_scope:" in message.get("content", "")
            for message in request["messages"]
        )
    )
    appeal_text = next(
        message["content"]
        for message in appeal_request["messages"]
        if message.get("role") == "user" and "R4_patch_scope:" in message.get("content", "")
    )
    assert r4.evidence in appeal_text
    assert first.claim_evidence in appeal_text
    assert "Fix the source so these checks pass." in appeal_text

    markdown = render(result)
    assert "**Verdict: VERIFIED**" in markdown
    assert "REJECTED" in markdown
    assert "tests/test_calc.py" in markdown
    assert "Changed the test and claimed success." in markdown
    assert "Restored the test, fixed the source, and ran the suite." in markdown

    kinds = [event.kind for event in events]
    appeal_index = kinds.index("appeal")
    assert kinds[:appeal_index].count("witness") == 1
    assert kinds[:appeal_index].count("check") == 6
    assert kinds[appeal_index + 1 :].count("witness") == 1
    assert kinds[appeal_index + 1 :].count("check") == 6
    assert kinds[appeal_index + 1] == "agent_tool"
    assert events[appeal_index].attempt == 1
    assert "R4_patch_scope" in events[appeal_index].message
    assert events[-1].kind == "verdict"
    assert events[-1].message == "VERIFIED"


async def test_agent_release_failure_after_result_is_recorded_and_returned(
    tmp_path: Path,
):
    model = _model(
        [
            _turn(
                _call(
                    "write_file",
                    {"path": "calc/__init__.py", "content": FIXED_CALC},
                    "write-source",
                ),
            ),
            _turn(
                _call(
                    "run_command",
                    {"command": "python -m pytest -q"},
                    "run-suite",
                ),
            ),
            _finish(
                "finish",
                summary="Fixed subtraction and ran the suite.",
                changed=["calc/__init__.py"],
                green=True,
            ),
        ],
    )

    result, run_dir, _, _ = await _run(
        tmp_path,
        model,
        fail_agent_release=True,
    )

    assert result.final_verdict.status == "PASS"
    assert result.cleanup_error == "RuntimeError: agent release failed"
    persisted = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert persisted["cleanup_error"] == "RuntimeError: agent release failed"


async def test_no_fix_after_one_appeal_selects_no_verified_patch(tmp_path: Path):
    model = _model(
        [
            _turn(
                _call(
                    "write_file",
                    {"path": "calc/__init__.py", "content": CALC},
                    "write-same-first",
                ),
            ),
            _finish(
                "finish-first",
                summary="Claimed the unchanged source was fixed.",
                changed=["calc/__init__.py"],
                green=True,
            ),
            _turn(
                _call(
                    "write_file",
                    {"path": "calc/__init__.py", "content": CALC},
                    "write-same-second",
                ),
            ),
            _finish(
                "finish-second",
                summary="Repeated the unchanged source after appeal.",
                changed=["calc/__init__.py"],
                green=True,
            ),
        ],
    )

    result, run_dir, _, _ = await _run(tmp_path, model)

    assert result.final_verdict.status == "REJECTED"
    assert [verdict.status for verdict in result.verdict_history] == [
        "REJECTED",
        "REJECTED",
    ]
    assert result.verified_fix is False
    assert result.selected_patch_path is None
    persisted = json.loads((run_dir / "result.json").read_text())
    assert persisted["verified_fix"] is False
    assert persisted["selected_patch_path"] is None
    assert len(persisted["attempts"]) == 2

    markdown = render(result)
    assert "**Verdict: NO VERIFIED FIX**" in markdown
    assert markdown.count("REJECTED") >= 2


async def test_checkpoint_tampering_does_not_release_a_synthetic_witness(tmp_path: Path):
    command = (
        "python -c \"from pathlib import Path; "
        "p=next(Path('..').glob('ckpt-*/tests/test_calc.py')); "
        "p.write_text('tampered\\n')\""
    )
    model = _model(
        [
            _turn(
                _call(
                    "run_command",
                    {"command": command},
                    "tamper-checkpoint",
                ),
            ),
            _finish(
                "finish",
                summary="No verified fix.",
                changed=[],
                green=False,
            ),
        ],
    )
    released: list[str] = []
    events = []

    result, run_dir, _, _ = await _run(
        tmp_path,
        model,
        appeals=0,
        released=released,
        progress=events.append,
    )

    assert result.final_verdict.status == "ERROR"
    assert released == ["base", "agent1"]
    assert (run_dir / "attempts" / "1" / "verdict.json").is_file()
    assert (run_dir / "result.json").is_file()
    witness = next(event for event in events if event.kind == "witness")
    assert "witness not provisioned" in witness.message
    assert "files applied none" in witness.message
    assert "apply failed (exit 1)" in witness.message
    assert "fresh sandbox" not in witness.message


async def test_reproduced_load_failure_is_rejected_and_appealed(tmp_path: Path):
    broken_calc = '''def add(a, b):
    return a + b


def sub(a, b):
    return (
'''
    model = _model(
        [
            _turn(
                _call(
                    "write_file",
                    {"path": "calc/__init__.py", "content": broken_calc},
                    "break-source",
                ),
            ),
            _finish(
                "finish-first",
                summary="Changed subtraction.",
                changed=["calc/__init__.py"],
                green=False,
            ),
            _turn(
                _call(
                    "write_file",
                    {"path": "calc/__init__.py", "content": FIXED_CALC},
                    "repair-source",
                ),
            ),
            _turn(
                _call(
                    "run_command",
                    {"command": "python -m pytest -q"},
                    "run-suite",
                ),
            ),
            _finish(
                "finish-second",
                summary="Corrected the syntax and subtraction.",
                changed=["calc/__init__.py"],
                green=True,
            ),
        ],
    )

    result, run_dir, _, model = await _run(
        tmp_path,
        model,
        root_conftest="import calc\n",
    )

    assert [verdict.status for verdict in result.verdict_history] == [
        "REJECTED",
        "PASS",
    ]
    first = result.verdict_history[0]
    r1 = next(
        predicate
        for predicate in first.predicates
        if predicate.id == "R1_fail_to_pass"
    )
    assert r1.evidence.startswith(
        "the suite could not load with this patch (pytest exit 4): ",
    )
    confirmation_path = (
        run_dir / "attempts" / "1" / "confirmation" / "receipts.jsonl"
    )
    confirmation = [
        json.loads(line)
        for line in confirmation_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [receipt["kind"] for receipt in confirmation] == [
        "apply",
        "verification",
    ]
    assert {receipt["branch_id"] for receipt in confirmation} == {"c1"}

    appeal_request = next(
        request
        for request in model.requests
        if request["kind"] == "chat"
        and any(
            message.get("role") == "user"
            and "the suite could not load with this patch" in message.get(
                "content",
                "",
            )
            for message in request["messages"]
        )
    )
    assert any(
        r1.evidence in (message.get("content") or "")
        for message in appeal_request["messages"]
    )


# R8: the independent review that can only object.

_PLAN = {
    "hypothesis": "calc.sub adds instead of subtracting",
    "files_to_edit": ["calc/__init__.py"],
    "approach": "Change calc.sub to subtract and run the suite.",
}
_OBJECTION = {
    "requirement": "calc.sub(5, 3) must return 2",
    "location": "calc/__init__.py:6",
    "problem": "the reviewer says the fix is incomplete",
}


def _fix_turns(suffix: str) -> list[AssistantTurn]:
    return [
        _turn(_call("write_file", {"path": "calc/__init__.py",
                                   "content": CALC.replace("a + b  # bug: should be a - b", "a - b")},
                    f"write-{suffix}")),
        _turn(_call("run_command", {"command": "python -m pytest -q"}, f"run-{suffix}")),
        _finish(f"finish-{suffix}", summary="Corrected subtraction.", changed=["calc/__init__.py"], green=True),
    ]


def _review_requests(model: FakeModel) -> list[dict]:
    return [request for request in model.requests
            if request["kind"] == "complete_json" and request["schema"].__name__ == "ReviewAnswer"]


async def test_review_objection_rejects_a_passing_patch_and_reaches_the_appeal(tmp_path: Path):
    model = FakeModel(json_objects=[_PLAN, {"objections": [_OBJECTION]}, {"objections": [_OBJECTION]},
                                    {"objections": []}, {"objections": []}],
                      turns=_fix_turns("first") + _fix_turns("second"))

    result, run_dir, _, _ = await _run(tmp_path, model, review="veto")

    first, second = result.verdict_history
    assert first.status == "REJECTED"
    r8 = next(p for p in first.predicates if p.id == "R8_review")
    assert r8.passed is False
    assert r8.evidence.startswith("2 of 2 independent reviews object: ")
    assert "calc.sub(5, 3) must return 2" in r8.evidence and "calc/__init__.py:6" in r8.evidence
    assert first.failed_predicate_ids() == ["R8_review"]
    assert second.status == "PASS"
    assert next(p for p in second.predicates if p.id == "R8_review").passed is True
    assert result.final_verdict.status == "PASS" and result.verified_fix is True
    appeal = next(request for request in reversed(model.requests) if request["kind"] == "chat")
    assert any("the reviewer says the fix is incomplete" in str(message.get("content"))
               for message in appeal["messages"])
    review = json.loads((run_dir / "attempts" / "1" / "review.json").read_text())
    assert review["veto"] is True and [vote["objections"] for vote in review["votes"]] == [[_OBJECTION]] * 2
    assert json.loads((run_dir / "attempts" / "2" / "review.json").read_text())["veto"] is False
    assert len(_review_requests(model)) == 4


async def test_review_without_objection_keeps_the_pass_and_orders_the_checks(tmp_path: Path):
    model = FakeModel(json_objects=[_PLAN, {"objections": []}, {"objections": []}], turns=_fix_turns("only"))

    result, _, _, _ = await _run(tmp_path, model, review="veto")

    assert result.final_verdict.status == "PASS"
    assert [p.id for p in result.final_verdict.predicates] == [
        "R1_fail_to_pass", "R2_pass_to_pass", "R3_no_shrink", "R4_patch_scope", "R5_provenance",
        "R7_no_shortcuts", "R8_review", "R6_claim_audit",
    ]
    assert next(p for p in result.final_verdict.predicates if p.id == "R8_review").evidence == "no objection"


async def test_ungrounded_objection_is_dropped_and_recorded(tmp_path: Path):
    paraphrase = dict(_OBJECTION, requirement="subtraction should be right")
    model = FakeModel(json_objects=[_PLAN, {"objections": [paraphrase]}, {"objections": []}],
                      turns=_fix_turns("only"))

    result, run_dir, _, _ = await _run(tmp_path, model, review="veto")

    assert result.final_verdict.status == "PASS"
    r8 = next(p for p in result.final_verdict.predicates if p.id == "R8_review")
    assert r8.evidence == "no objection (1 ungrounded objection(s) dropped)"
    assert json.loads((run_dir / "attempts" / "1" / "review.json").read_text())["votes"][0]["dropped"] == [paraphrase]


async def test_one_objecting_review_out_of_two_does_not_veto(tmp_path: Path):
    model = FakeModel(json_objects=[_PLAN, {"objections": [_OBJECTION]}, {"objections": []}],
                      turns=_fix_turns("only"))

    result, run_dir, _, _ = await _run(tmp_path, model, review="veto")

    assert result.final_verdict.status == "PASS"
    r8 = next(p for p in result.final_verdict.predicates if p.id == "R8_review")
    assert r8.passed is True and r8.evidence.startswith("no veto (1 of 2 independent reviews object): ")
    assert json.loads((run_dir / "attempts" / "1" / "review.json").read_text())["veto"] is False


async def test_a_failed_review_does_not_veto(tmp_path: Path):
    model = FakeModel(json_objects=[_PLAN], turns=_fix_turns("only"))  # no scripted review answer

    result, _, _, _ = await _run(tmp_path, model, review="veto")

    assert result.final_verdict.status == "PASS"
    r8 = next(p for p in result.final_verdict.predicates if p.id == "R8_review")
    assert r8.passed is True and "review unavailable" in r8.evidence


async def test_the_reviewer_never_sees_a_rejected_patch(tmp_path: Path):
    model = FakeModel(json_objects=[_PLAN], turns=[
        _turn(_call("write_file", {"path": "calc/__init__.py", "content": CALC}, "same")),
        _finish("finish", summary="Claimed a fix.", changed=["calc/__init__.py"], green=True),
    ])

    result, _, _, _ = await _run(tmp_path, model, appeals=0, review="veto")

    assert result.final_verdict.status == "REJECTED"
    assert "R8_review" not in [p.id for p in result.final_verdict.predicates]
    assert _review_requests(model) == []


async def test_review_is_off_by_default_in_the_library(tmp_path: Path):
    model = FakeModel(json_objects=[_PLAN], turns=_fix_turns("only"))

    result, run_dir, _, _ = await _run(tmp_path, model)

    assert "R8_review" not in [p.id for p in result.final_verdict.predicates]
    assert _review_requests(model) == []
    assert not (run_dir / "attempts" / "1" / "review.json").exists()
    assert json.loads((run_dir / "input.json").read_text())["review"] == "off"


async def test_review_tokens_are_counted_in_the_run_cost(tmp_path: Path):
    from receipts.cost import TokenUsage
    from receipts.verify.review import ReviewAnswer

    answer = ReviewAnswer(objections=[], usage=TokenUsage(prompt=100_000, completion=1_000))
    with_review = FakeModel(json_objects=[_PLAN, answer, answer], turns=_fix_turns("only"))
    without_review = FakeModel(json_objects=[_PLAN], turns=_fix_turns("only"))

    _, reviewed_dir, _, _ = await _run(tmp_path / "with", with_review, review="veto")
    _, plain_dir, _, _ = await _run(tmp_path / "without", without_review)

    reviewed = json.loads((reviewed_dir / "cost.json").read_text())
    plain = json.loads((plain_dir / "cost.json").read_text())
    (name, usage), = reviewed["models"].items()
    assert usage["prompt_tokens"] - plain["models"][name]["prompt_tokens"] == 200_000
    assert usage["completion_tokens"] - plain["models"][name]["completion_tokens"] == 2_000


async def test_advisory_review_records_objections_without_changing_the_verdict(tmp_path: Path):
    model = FakeModel(json_objects=[_PLAN, {"objections": [_OBJECTION]}, {"objections": [_OBJECTION]}],
                      turns=_fix_turns("only"))

    result, run_dir, _, _ = await _run(tmp_path, model, review="advisory")

    assert [verdict.status for verdict in result.verdict_history] == ["PASS"]
    assert result.final_verdict.status == "PASS" and result.verified_fix is True
    advisory = next(p for p in result.final_verdict.predicates if p.id == "R8_review_advisory")
    assert advisory.passed is False and advisory.evidence.startswith("advisory: 2 of 2 independent reviews object: ")
    assert "R8_review" not in [p.id for p in result.final_verdict.predicates]
    assert result.final_verdict.failed_predicate_ids() == []
    assert json.loads((run_dir / "attempts" / "1" / "review.json").read_text())["veto"] is True
    assert [p.id for p in result.final_verdict.predicates][-2:] == ["R8_review_advisory", "R6_claim_audit"]


async def test_advisory_review_without_objection(tmp_path: Path):
    model = FakeModel(json_objects=[_PLAN, {"objections": []}, {"objections": []}], turns=_fix_turns("only"))

    result, _, _, _ = await _run(tmp_path, model, review="advisory")

    advisory = next(p for p in result.final_verdict.predicates if p.id == "R8_review_advisory")
    assert advisory.passed is True and advisory.evidence == "advisory: no objection"


def test_run_inputs_written_before_review_modes_still_load():
    orchestrate = _orchestrate_module()
    base = {"source": {}, "issue": "x", "spec_tests": [], "suite_scope": "tests", "appeals": 1,
            "budgets": orchestrate.RunBudgets().model_dump()}
    assert orchestrate.RunInput.model_validate({**base, "review": False}).review == "off"
    assert orchestrate.RunInput.model_validate({**base, "review": True}).review == "veto"
    assert orchestrate.RunInput.model_validate(base).review == "off"


async def test_a_reviewer_with_its_own_meter_counts_every_call(tmp_path: Path):
    from receipts.cost import CostMeter, TokenUsage

    class MeteredReviewer(FakeModel):
        config = {"model": SUPER_MODEL}

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._meter = CostMeter()

        async def complete_json(self, system, user, schema):
            # Two paid calls behind one answer, as a retry after invalid JSON would be.
            self._meter.add_usage(SUPER_MODEL, TokenUsage(prompt=50_000, completion=500))
            self._meter.add_usage(SUPER_MODEL, TokenUsage(prompt=50_000, completion=500))
            return await super().complete_json(system, user, schema)

    reviewer = MeteredReviewer(json_objects=[{"objections": []}, {"objections": []}])
    with_review = FakeModel(json_objects=[_PLAN], turns=_fix_turns("only"))
    plain = FakeModel(json_objects=[_PLAN], turns=_fix_turns("only"))

    _, reviewed_dir, _, _ = await _run(tmp_path / "with", with_review, review="advisory", reviewer=reviewer)
    _, plain_dir, _, _ = await _run(tmp_path / "without", plain)

    reviewed = json.loads((reviewed_dir / "cost.json").read_text())["models"]
    base = json.loads((plain_dir / "cost.json").read_text())["models"]
    name = next(iter(base))
    assert reviewed[SUPER_MODEL]["prompt_tokens"] - (base[name]["prompt_tokens"] if name == SUPER_MODEL else 0) == 200_000


async def test_the_receipt_lists_every_review_objection(tmp_path: Path):
    other = dict(_OBJECTION, problem="the second reviewer names a different gap")
    model = FakeModel(json_objects=[_PLAN, {"objections": [_OBJECTION]}, {"objections": [other]}],
                      turns=_fix_turns("only"))

    result, _, _, _ = await _run(tmp_path, model, review="advisory")

    advisory = next(p for p in result.final_verdict.predicates if p.id == "R8_review_advisory")
    assert "the reviewer says the fix is incomplete" in advisory.evidence
    assert "the second reviewer names a different gap" in advisory.evidence


async def test_one_objecting_review_is_shown_without_a_veto(tmp_path: Path):
    model = FakeModel(json_objects=[_PLAN, {"objections": [_OBJECTION]}, {"objections": []}],
                      turns=_fix_turns("only"))

    result, _, _, _ = await _run(tmp_path, model, review="advisory")

    advisory = next(p for p in result.final_verdict.predicates if p.id == "R8_review_advisory")
    assert advisory.passed is True
    assert advisory.evidence.startswith("advisory: no veto (1 of 2 independent reviews object): ")
    assert "the reviewer says the fix is incomplete" in advisory.evidence
