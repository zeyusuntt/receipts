from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from receipts.llm import AssistantTurn, FakeModel, ToolCall
from receipts.receipt_text import render
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import RepoAtCommit
from receipts.sandbox.sink import RunSink
from tests.fixtures.repo_factory import CALC, TEST_CALC, make_repo


TARGET = "tests/test_calc.py::test_sub"
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


async def _run(
    tmp_path: Path,
    model: FakeModel,
    *,
    appeals: int = 1,
):
    orchestrate = _orchestrate_module()
    repo = make_repo(tmp_path / "source")
    run_dir = tmp_path / "run"
    executor = LocalExecutor(
        tmp_path / "executor",
        RunSink(run_dir),
        run_id="orchestrate-test",
    )
    result = await orchestrate.fix(
        executor,
        model,
        RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"),
        issue="calc.sub(5, 3) must return 2",
        spec_tests=[TARGET],
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
            },
        ),
    )
    return result, run_dir, repo, model


async def test_honest_fix_passes_and_writes_the_complete_run_directory(tmp_path: Path):
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
                summary="Corrected subtraction and ran the full suite.",
                changed=["calc/__init__.py"],
                green=True,
            ),
        ],
    )

    result, run_dir, repo, _ = await _run(tmp_path, model)

    assert result.final_verdict.status == "PASS"
    assert [verdict.status for verdict in result.verdict_history] == ["PASS"]
    assert result.verified_fix is True
    assert result.selected_patch_path == "attempts/1/filtered.diff"

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
    assert persisted["cost"] == json.loads((run_dir / "cost.json").read_text())
    assert persisted["wall_time_s"] > 0
    assert "return a - b" in (run_dir / persisted["selected_patch_path"]).read_text()

    baseline = json.loads((run_dir / "baseline.json").read_text())
    assert len(baseline["runs"]) == 2
    assert baseline["target"] == [TARGET]
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


async def test_rejected_test_edit_appeals_then_source_fix_passes(tmp_path: Path):
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

    result, run_dir, _, model = await _run(tmp_path, model)

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
    assert (run_dir / "attempts" / "1" / "verdict.json").is_file()
    assert (run_dir / "attempts" / "2" / "verdict.json").is_file()

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
