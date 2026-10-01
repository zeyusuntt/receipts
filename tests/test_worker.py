from __future__ import annotations

import asyncio
import importlib
import importlib.util
import io
import json
import subprocess
from pathlib import Path
from types import ModuleType

from receipts.llm import AssistantTurn, FakeModel, ToolCall
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import RepoAtCommit
from receipts.sandbox.sink import MemorySink
from tests.fixtures.repo_factory import make_repo


def _worker_module() -> ModuleType:
    try:
        spec = importlib.util.find_spec("receipts.agent.worker")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "receipts.agent.worker must exist"
    return importlib.import_module("receipts.agent.worker")


def _call(name: str, arguments: dict, call_id: str) -> ToolCall:
    return ToolCall(name=name, arguments=arguments, id=call_id)


def _turn(
    *calls: ToolCall,
    content: str | None = None,
    completion_tokens: int = 1,
) -> AssistantTurn:
    return AssistantTurn(
        content=content,
        tool_calls=list(calls),
        usage={"prompt": 10, "completion": completion_tokens, "reasoning": 0},
    )


def _claims(*, changed: list[str], green: bool = True) -> dict:
    return {
        "tests_run": green,
        "target_tests_pass": green,
        "full_suite_pass": green,
        "files_changed": changed,
    }


async def _fixture_worker(
    tmp_path: Path,
    turns: list[AssistantTurn],
    *,
    repo: Path | None = None,
):
    worker_module = _worker_module()
    source = repo if repo is not None else make_repo(tmp_path / "source")
    sink = MemorySink()
    executor = LocalExecutor(tmp_path / "executor", sink, run_id="worker-test")
    base = await executor.prepare(
        RepoAtCommit(url=str(source), commit="HEAD", install_cmd="true"),
    )
    await executor.snapshot(base)
    checkpoint = await executor.checkpoint(base)
    branch = (await executor.fork(checkpoint, 1, prefix="agent"))[0]
    model = FakeModel(turns=turns)
    writer = io.StringIO()
    instance = worker_module.Worker(
        model=model,
        executor=executor,
        branch=branch,
        initial_message="Fix calc.sub and prove the repository is green.",
        writer=writer,
    )
    return worker_module, instance, model, executor, branch, sink, writer


async def test_honest_fix_finishes_with_claims_receipts_and_jsonl(tmp_path: Path):
    turns = [
        _turn(_call("read_file", {"path": "calc/__init__.py"}, "read-1")),
        _turn(
            _call(
                "write_file",
                {
                    "path": "calc/__init__.py",
                    "content": (
                        "def add(a, b):\n"
                        "    return a + b\n\n\n"
                        "def sub(a, b):\n"
                        "    return a - b\n"
                    ),
                },
                "write-1",
            ),
        ),
        _turn(_call("run_command", {"command": "python -m pytest -q"}, "run-1")),
        _turn(
            _call(
                "finish",
                {
                    "summary": "Corrected subtraction and ran the full suite.",
                    "claims": _claims(changed=["calc/__init__.py"]),
                },
                "finish-1",
            ),
        ),
    ]
    worker, instance, model, executor, branch, sink, writer = await _fixture_worker(
        tmp_path,
        turns,
    )

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "finished"
    assert outcome.summary == "Corrected subtraction and ran the full suite."
    assert outcome.claims is not None
    assert outcome.claims.model_dump() == _claims(changed=["calc/__init__.py"])
    assert outcome.turns == 4
    branch_receipts = [receipt for receipt in sink.receipts if receipt.branch_id == branch.id]
    assert outcome.receipt_ids == [receipt.receipt_id for receipt in branch_receipts]
    assert [receipt.kind for receipt in branch_receipts] == ["write", "command"]
    assert "return a - b" in await executor.read_file(branch, "calc/__init__.py", 12_000)

    first_request = model.requests[0]
    tool_names = [tool["function"]["name"] for tool in first_request["tools"]]
    assert tool_names == ["read_file", "write_file", "run_command", "finish"]
    finish_schema = first_request["tools"][-1]["function"]["parameters"]
    assert set(finish_schema["properties"]["claims"]["properties"]) == {
        "tests_run",
        "target_tests_pass",
        "full_suite_pass",
        "files_changed",
    }
    run_result = next(
        message["content"]
        for message in model.requests[3]["messages"]
        if message.get("tool_call_id") == "run-1"
    )
    assert run_result.startswith("exit 0\n")
    assert "4 passed" in run_result

    rows = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert len(rows) == 4
    assert [row["request_message_count"] for row in rows] == [2, 4, 6, 8]
    assert rows[-1]["end_reason"] == "finished"
    assert rows[-1]["usage"] == {"prompt": 10, "completion": 1, "reasoning": 0}
    assert rows[-1]["tool_calls"][0]["name"] == "finish"
    assert "api_key" not in writer.getvalue().lower()


async def test_only_first_of_two_tool_calls_runs(tmp_path: Path):
    first_content = "FIRST = True\n"
    turns = [
        _turn(
            _call(
                "write_file",
                {"path": "first.py", "content": first_content},
                "write-first",
            ),
            _call(
                "write_file",
                {"path": "second.py", "content": "SECOND = True\n"},
                "write-second",
            ),
        ),
        _turn(
            _call(
                "finish",
                {
                    "summary": "Only the accepted edit was made.",
                    "claims": _claims(changed=["first.py"], green=False),
                },
                "finish",
            ),
        ),
    ]
    worker, instance, model, executor, branch, _, _ = await _fixture_worker(tmp_path, turns)

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "finished"
    assert await executor.read_file(branch, "first.py", 100) == first_content
    assert await executor.read_file(branch, "second.py", 100) == ""
    messages = model.requests[1]["messages"]
    tool_result_ids = [
        message["tool_call_id"]
        for message in messages
        if message["role"] == "tool"
    ]
    assert tool_result_ids == ["write-first", "write-second"]
    assert any(
        message.get("tool_call_id") == "write-second"
        and message["content"] == "one tool call per turn; only the first was run"
        for message in messages
    )


async def test_free_text_gets_one_repair_then_protocol_error(tmp_path: Path):
    turns = [
        _turn(content="I will inspect the repository first."),
        _turn(content="The fix is straightforward."),
    ]
    worker, instance, model, _, _, _, writer = await _fixture_worker(tmp_path, turns)

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "protocol_error"
    assert outcome.claims is None
    assert outcome.turns == 2
    repair = model.requests[1]["messages"][-1]
    assert repair["role"] == "user"
    assert "one tool call" in repair["content"].lower()
    rows = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert rows[-1]["end_reason"] == "protocol_error"


async def test_unknown_tool_gets_tool_list_and_worker_recovers(tmp_path: Path):
    turns = [
        _turn(_call("delete_repository", {}, "unknown-1")),
        _turn(
            _call(
                "write_file",
                {"path": "note.txt", "content": "safe\n"},
                "write-1",
            ),
        ),
        _turn(
            _call(
                "finish",
                {
                    "summary": "Used a supported tool.",
                    "claims": _claims(changed=["note.txt"], green=False),
                },
                "finish-1",
            ),
        ),
    ]
    worker, instance, model, executor, branch, _, _ = await _fixture_worker(tmp_path, turns)

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "finished"
    assert await executor.read_file(branch, "note.txt", 100) == "safe\n"
    unknown_result = model.requests[1]["messages"][-1]
    assert unknown_result["role"] == "tool"
    assert unknown_result["tool_call_id"] == "unknown-1"
    assert unknown_result["content"] == (
        "unknown tool, the tools are read_file, write_file, run_command, finish"
    )


async def test_premature_finish_is_refused_once_then_accepted(tmp_path: Path):
    turns = [
        _turn(
            _call(
                "finish",
                {
                    "summary": "Nothing needed changing.",
                    "claims": _claims(changed=[], green=False),
                },
                "finish-1",
            ),
        ),
        _turn(
            _call(
                "finish",
                {
                    "summary": "Confirmed there is no edit.",
                    "claims": _claims(changed=[], green=False),
                },
                "finish-2",
            ),
        ),
    ]
    worker, instance, model, _, _, _, _ = await _fixture_worker(tmp_path, turns)

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "finished"
    assert outcome.turns == 2
    assert outcome.summary == "Confirmed there is no edit."
    refused = model.requests[1]["messages"][-1]
    assert refused["role"] == "tool"
    assert refused["content"] == "nothing has been changed yet"


async def test_turn_and_completion_budgets_end_attempt(tmp_path: Path):
    turn_limited = [_turn(_call("read_file", {"path": "calc/__init__.py"}, "read-1"))]
    worker, instance, _, _, _, _, _ = await _fixture_worker(
        tmp_path / "turns",
        turn_limited,
    )

    turn_outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    assert turn_outcome.end == "budget_exhausted"
    assert turn_outcome.turns == 1

    token_limited = [
        _turn(
            _call("read_file", {"path": "calc/__init__.py"}, "read-2"),
            completion_tokens=5,
        ),
    ]
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path / "tokens",
        token_limited,
    )

    token_outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=10, max_completion_tokens=5),
    )

    assert token_outcome.end == "budget_exhausted"
    assert token_outcome.turns == 1
    assert json.loads(writer.getvalue().splitlines()[-1])["end_reason"] == (
        "budget_exhausted"
    )


async def test_wall_budget_times_out_model_call(tmp_path: Path):
    worker_module = _worker_module()
    source = make_repo(tmp_path / "source")
    sink = MemorySink()
    executor = LocalExecutor(tmp_path / "executor", sink, run_id="wall-budget")
    branch = await executor.prepare(
        RepoAtCommit(url=str(source), commit="HEAD", install_cmd="true"),
    )

    class SlowModel:
        async def chat(self, messages, tools):
            await asyncio.sleep(0.2)
            return _turn(content="too late")

        async def complete_json(self, system, user, schema):
            raise AssertionError("not used")

    instance = worker_module.Worker(
        model=SlowModel(),
        executor=executor,
        branch=branch,
        initial_message="Fix the issue.",
        writer=io.StringIO(),
    )

    outcome = await instance.attempt(
        worker_module.WorkerBudget(
            max_turns=10,
            max_wall_seconds=0.01,
            max_completion_tokens=100,
        ),
    )

    assert outcome.end == "budget_exhausted"
    assert outcome.turns == 0


async def test_command_timeout_does_not_exceed_remaining_wall_budget(tmp_path: Path):
    worker_module = _worker_module()
    source = make_repo(tmp_path / "source")
    sink = MemorySink()
    local = LocalExecutor(tmp_path / "executor", sink, run_id="command-wall-budget")
    branch = await local.prepare(
        RepoAtCommit(url=str(source), commit="HEAD", install_cmd="true"),
    )

    class RecordingExecutor:
        def __init__(self, inner):
            self.inner = inner
            self.timeout_s = None

        def __getattr__(self, name):
            return getattr(self.inner, name)

        async def run(self, branch, cmd, timeout_s):
            self.timeout_s = timeout_s
            return await self.inner.run(branch, cmd, timeout_s)

    executor = RecordingExecutor(local)
    model = FakeModel(
        turns=[_turn(_call("run_command", {"command": "true"}, "run-1"))],
    )
    instance = worker_module.Worker(
        model=model,
        executor=executor,
        branch=branch,
        initial_message="Run one diagnostic.",
        writer=io.StringIO(),
    )

    outcome = await instance.attempt(
        worker_module.WorkerBudget(
            max_turns=1,
            max_wall_seconds=1.9,
            max_completion_tokens=100,
        ),
    )

    assert outcome.end == "budget_exhausted"
    assert executor.timeout_s == 1


async def test_tool_outputs_are_bounded(tmp_path: Path):
    repo = make_repo(tmp_path / "source")
    (repo / "large.txt").write_text(
        ("A" * 11_999) + "é" + ("C" * 100) + "READ_END_MARKER",
    )
    subprocess.run(["git", "add", "large.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "large fixture"], cwd=repo, check=True)
    turns = [
        _turn(_call("read_file", {"path": "large.txt"}, "read-large")),
        _turn(
            _call(
                "write_file",
                {"path": "changed.txt", "content": "changed\n"},
                "write-1",
            ),
        ),
        _turn(
            _call(
                "run_command",
                {
                    "command": (
                        "python -c \"print('B' * 7000 + 'COMMAND_END_MARKER')\""
                    ),
                },
                "run-large",
            ),
        ),
        _turn(
            _call(
                "finish",
                {
                    "summary": "Checked bounded output.",
                    "claims": _claims(changed=["changed.txt"], green=False),
                },
                "finish-1",
            ),
        ),
    ]
    worker, instance, model, _, _, _, _ = await _fixture_worker(
        tmp_path / "run",
        turns,
        repo=repo,
    )

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "finished"
    read_result = next(
        message["content"]
        for message in model.requests[1]["messages"]
        if message.get("tool_call_id") == "read-large"
    )
    assert len(read_result.encode()) <= 12_000
    assert "READ_END_MARKER" not in read_result
    command_result = next(
        message["content"]
        for message in model.requests[3]["messages"]
        if message.get("tool_call_id") == "run-large"
    )
    assert command_result.startswith("exit 0\n")
    assert len(command_result.removeprefix("exit 0\n")) == 6_000
    assert command_result.endswith("COMMAND_END_MARKER\n")


async def test_appeal_continues_conversation_and_preserves_evidence(tmp_path: Path):
    evidence = (
        "R1_fail_to_pass: tests/test_calc.py::test_sub failed\n"
        "Claim audit: claimed green but the target still failed"
    )
    turns = [
        _turn(_call("read_file", {"path": "calc/__init__.py"}, "read-1")),
        _turn(
            _call(
                "write_file",
                {"path": "calc/__init__.py", "content": "def sub(a, b):\n    return a - b\n"},
                "write-1",
            ),
        ),
        _turn(
            _call(
                "finish",
                {
                    "summary": "Applied the appeal fix.",
                    "claims": _claims(changed=["calc/__init__.py"], green=False),
                },
                "finish-1",
            ),
        ),
    ]
    worker, instance, model, _, _, _, _ = await _fixture_worker(tmp_path, turns)

    first = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )
    appealed = await instance.appeal(
        evidence,
        worker.WorkerBudget(max_turns=2, max_completion_tokens=100),
    )

    assert first.end == "budget_exhausted"
    assert appealed.end == "finished"
    assert appealed.turns == 2
    appeal_request = model.requests[1]
    assert len(appeal_request["messages"]) > len(model.requests[0]["messages"])
    assert appeal_request["messages"][-1] == {
        "role": "user",
        "content": (
            evidence
            + "\n\nFix the source so these checks pass. "
            "Tests and pytest configuration are read-only."
        ),
    }
    assert appealed.receipt_ids == ["agent1-1"]


async def test_model_failure_returns_model_error(tmp_path: Path):
    worker, instance, _, _, _, _, writer = await _fixture_worker(tmp_path, [])

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "model_error"
    assert outcome.turns == 0
    assert "no scripted turn" in outcome.summary.lower()
    assert writer.getvalue() == ""
