from __future__ import annotations

import asyncio
import copy
import importlib
import importlib.util
import io
import json
import math
import re
import shlex
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from receipts.llm import AssistantTurn, FakeModel, MalformedToolCall, ToolCall
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
    finish_reason: str | None = None,
) -> AssistantTurn:
    return AssistantTurn(
        content=content,
        tool_calls=list(calls),
        usage={"prompt": 10, "completion": completion_tokens, "reasoning": 0},
        finish_reason=finish_reason,
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
    repo_root: str | None = None,
    scratch_path: str | None = None,
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
    worker_kwargs = {}
    if scratch_path is not None:
        worker_kwargs["scratch_path"] = scratch_path
    instance = worker_module.Worker(
        model=model,
        executor=executor,
        branch=branch,
        initial_message="Fix calc.sub and prove the repository is green.",
        writer=writer,
        repo_root=repo_root,
        **worker_kwargs,
    )
    return worker_module, instance, model, executor, branch, sink, writer


class _RecordingExecutor:
    def __init__(self, inner):
        self.inner = inner
        self.routes: list[tuple[str, str]] = []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def run(self, branch, command, timeout_s):
        self.routes.append(("run", command))
        return await self.inner.run(branch, command, timeout_s)

    async def run_pytest(self, branch, args, timeout_s):
        self.routes.append(("pytest", args))
        return await self.inner.run_pytest(branch, args, timeout_s)


def _record_executor(instance, executor) -> _RecordingExecutor:
    recording = _RecordingExecutor(executor)
    instance.executor = recording
    return recording


def _result(instance, call_id: str) -> str:
    return next(
        message["content"]
        for message in instance.messages
        if message.get("tool_call_id") == call_id
    )


def _logged_result(writer: io.StringIO, call_id: str) -> dict:
    rows = [json.loads(line) for line in writer.getvalue().splitlines()]
    return next(
        result
        for row in rows
        for result in row["results"]
        if result["id"] == call_id
    )


def _assert_logged_result(
    writer: io.StringIO,
    *,
    call_id: str,
    name: str,
    ran_as: str | None,
    executed: bool,
    result_class: str,
    reply: str,
) -> None:
    assert _logged_result(writer, call_id) == {
        "id": call_id,
        "name": name,
        "ran_as": ran_as,
        "executed": executed,
        "class": result_class,
        "result_bytes": len(reply.encode("utf-8")),
    }


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("pytest", ""),
        ("pytest -q tests/test_calc.py::test_sub", "-q tests/test_calc.py::test_sub"),
        ("python -m pytest -v tests/", "-v tests/"),
        ("python3 -m pytest", ""),
        ("python3.12 -m pytest -k \"a and b\"", "-k 'a and b'"),
        ("/usr/bin/python3 -m pytest", ""),
        ("py.test tests/x.py::T::t[args0]", "'tests/x.py::T::t[args0]'"),
        ("cd tests && pytest", None),
        ("pytest | tail -5", None),
        ("pytest > out.txt", None),
        ("pytest; echo done", None),
        ("echo pytest", None),
        ("python -c \"import pytest\"", None),
        ("pip install pytest", None),
        ("pytest $(ls tests)", None),
        ("pytest \"unbalanced", None),
        ("python -m pip install pytest", None),
    ],
)
def test_pytest_args_recognizes_only_plain_pytest_invocations(
    command: str,
    expected: str | None,
):
    assert _worker_module().pytest_args(command) == expected


@pytest.mark.parametrize(
    ("command", "repo_root", "expected"),
    [
        ("cd /repo && python -m pytest -q", "/repo", "-q"),
        ("cd /repo/./ && pytest", "/repo", ""),
        ("cd . && pytest tests", "/repo", "tests"),
        ("cd . && pytest tests", None, "tests"),
        ("cd tests && pytest", "/repo", None),
        ("cd /other && pytest", "/repo", None),
        ("cd /repo && pytest", None, None),
        ("cd /repo && pytest | tail -5", "/repo", None),
        ("cd /repo && cd . && pytest", "/repo", None),
    ],
)
def test_pytest_args_allows_one_trusted_leading_cd(
    command: str,
    repo_root: str | None,
    expected: str | None,
):
    assert _worker_module().pytest_args(command, repo_root=repo_root) == expected


@pytest.mark.parametrize(
    ("alias", "argument_name"),
    [
        ("execute", "command"),
        ("bash", "cmd"),
        ("shell", "script"),
        ("run", "command"),
        ("terminal", "cmd"),
        ("execute_command", "script"),
        ("execute_bash", "command"),
    ],
)
async def test_command_aliases_run_as_run_command_without_protocol_strike(
    tmp_path: Path,
    alias: str,
    argument_name: str,
):
    command = "printf alias-command"
    turns = [
        _turn(content="first protocol error"),
        _turn(content="second protocol error"),
        _turn(_call(alias, {argument_name: command}, "alias-command")),
    ]
    worker, instance, _, executor, _, _, _ = await _fixture_worker(tmp_path, turns)
    recording = _record_executor(instance, executor)

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=3, max_completion_tokens=100),
    )

    assert outcome.end == "budget_exhausted"
    assert recording.routes == [("run", command)]
    assert _result(instance, "alias-command").startswith(
        "(alias for run_command)\nexit 0\n",
    )


@pytest.mark.parametrize("alias", ["execute_grep", "grep", "search"])
async def test_grep_aliases_run_as_quoted_run_command_without_protocol_strike(
    tmp_path: Path,
    alias: str,
):
    turns = [
        _turn(content="first protocol error"),
        _turn(content="second protocol error"),
        _turn(
            _call(
                alias,
                {"pattern": "return a", "path": "calc"},
                "alias-grep",
            ),
        ),
    ]
    worker, instance, _, executor, _, _, _ = await _fixture_worker(tmp_path, turns)
    recording = _record_executor(instance, executor)

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=3, max_completion_tokens=100),
    )

    assert outcome.end == "budget_exhausted"
    assert recording.routes == [("run", "grep -rn -- 'return a' calc")]
    assert _result(instance, "alias-grep").startswith(
        "(alias for run_command)\nexit 0\n",
    )


@pytest.mark.parametrize(
    ("alias", "arguments", "expected"),
    [
        ("list_dir", {"path": "calc"}, "ls -la -- calc"),
        ("ls", {}, "ls -la -- ."),
    ],
)
async def test_list_aliases_run_as_quoted_run_command_without_protocol_strike(
    tmp_path: Path,
    alias: str,
    arguments: dict,
    expected: str,
):
    turns = [
        _turn(content="first protocol error"),
        _turn(content="second protocol error"),
        _turn(_call(alias, arguments, "alias-list")),
    ]
    worker, instance, _, executor, _, _, _ = await _fixture_worker(tmp_path, turns)
    recording = _record_executor(instance, executor)

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=3, max_completion_tokens=100),
    )

    assert outcome.end == "budget_exhausted"
    assert recording.routes == [("run", expected)]
    assert _result(instance, "alias-list").startswith(
        "(alias for run_command)\nexit 0\n",
    )


async def test_str_replace_editor_aliases_use_real_file_tools_without_strikes(
    tmp_path: Path,
):
    old_text = "    return a + b  # bug: should be a - b\n"
    new_text = "    return a - b\n"
    turns = [
        _turn(content="view error one"),
        _turn(content="view error two"),
        _turn(
            _call(
                "str_replace_editor",
                {"command": "view", "path": "calc/__init__.py"},
                "editor-view",
            ),
        ),
        _turn(content="edit error one"),
        _turn(content="edit error two"),
        _turn(
            _call(
                "str_replace_editor",
                {
                    "command": "str_replace",
                    "path": "calc/__init__.py",
                    "old_text": old_text,
                    "new_text": new_text,
                },
                "editor-replace",
            ),
        ),
        _turn(content="create error one"),
        _turn(content="create error two"),
        _turn(
            _call(
                "str_replace_editor",
                {
                    "command": "create",
                    "path": "created.txt",
                    "file_text": "created\n",
                },
                "editor-create",
            ),
        ),
    ]
    worker, instance, _, executor, branch, _, _ = await _fixture_worker(tmp_path, turns)

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=9, max_completion_tokens=100),
    )

    assert outcome.end == "budget_exhausted"
    assert "return a - b" in await executor.read_file(
        branch,
        "calc/__init__.py",
        2_000_000,
    )
    assert await executor.read_file(branch, "created.txt", 100) == "created\n"
    assert _result(instance, "editor-view").startswith("(alias for read_file)\n")
    assert _result(instance, "editor-replace") == "(alias for edit_file)\nok"
    assert _result(instance, "editor-create") == "(alias for write_file)\nok"


async def test_editor_alias_with_non_string_command_is_a_strike_not_a_crash(tmp_path: Path):
    turns = [
        _turn(_call("str_replace_editor", {"command": ["view"], "path": "calc/__init__.py"}, "bad-1")),
        _turn(_call("str_replace_editor", {"command": {"view": 1}, "path": "calc/__init__.py"}, "bad-2")),
        _turn(_call("str_replace_editor", {"command": None, "path": "calc/__init__.py"}, "bad-3")),
    ]
    worker, instance, _, _, _, _, _ = await _fixture_worker(tmp_path, turns)

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=9, max_completion_tokens=100),
    )

    assert outcome.end == "protocol_error"
    assert "invalid tool arguments" in _result(instance, "bad-1")


async def test_editor_view_alias_keeps_the_requested_line_range(tmp_path: Path):
    turns = [
        _turn(
            _call(
                "str_replace_editor",
                {"command": "view", "path": "calc/__init__.py", "view_range": [2, 2]},
                "editor-view-range",
            ),
        ),
    ]
    worker, instance, _, executor, branch, _, _ = await _fixture_worker(tmp_path, turns)
    whole = await executor.read_file(branch, "calc/__init__.py", 2_000_000)

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    result = _result(instance, "editor-view-range")
    assert result.startswith("(alias for read_file)\n")
    assert whole.splitlines()[1] in result
    assert whole.splitlines()[0] not in result


async def test_think_alias_is_noted_without_action_or_protocol_strike(tmp_path: Path):
    turns = [
        _turn(content="first protocol error"),
        _turn(content="second protocol error"),
        _turn(_call("think", {"anything": ["is", "accepted"]}, "think-1")),
        _turn(content="third protocol error"),
        _turn(content="fourth protocol error"),
    ]
    worker, instance, _, executor, branch, sink, _ = await _fixture_worker(
        tmp_path,
        turns,
    )
    recording = _record_executor(instance, executor)

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=5, max_completion_tokens=100),
    )

    assert outcome.end == "budget_exhausted"
    assert _result(instance, "think-1") == "noted"
    assert recording.routes == []
    assert not [
        receipt for receipt in sink.receipts if receipt.branch_id == branch.id
    ]


async def test_grep_alias_quotes_shell_metacharacters_as_one_literal_argument(
    tmp_path: Path,
):
    pattern = "'; rm -rf /"
    turns = [
        _turn(
            _call(
                "execute_grep",
                {"pattern": pattern},
                "grep-injection",
            ),
        ),
    ]
    worker, instance, _, executor, _, _, _ = await _fixture_worker(tmp_path, turns)
    recording = _record_executor(instance, executor)

    await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    expected = f"grep -rn -- {shlex.quote(pattern)} {shlex.quote('.')}"
    assert recording.routes == [("run", expected)]


@pytest.mark.parametrize(
    ("alias", "arguments", "expected"),
    [
        (
            "grep",
            {"pattern": "-needle", "path": "-directory"},
            "grep -rn -- -needle -directory",
        ),
        ("list_dir", {"path": "-directory"}, "ls -la -- -directory"),
    ],
)
async def test_shell_alias_dash_arguments_are_protected_by_double_dash(
    tmp_path: Path,
    alias: str,
    arguments: dict,
    expected: str,
):
    turns = [_turn(_call(alias, arguments, "dash-argument"))]
    worker, instance, _, executor, _, _, _ = await _fixture_worker(tmp_path, turns)
    recording = _record_executor(instance, executor)

    await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    assert recording.routes == [("run", expected)]


@pytest.mark.parametrize(
    ("alias", "arguments"),
    [
        ("grep", {"pattern": "line\nbreak"}),
        ("grep", {"pattern": "needle", "path": "line\nbreak"}),
        ("list_dir", {"path": "line\nbreak"}),
        ("grep", {"pattern": "nul\x00byte"}),
        ("grep", {"pattern": "needle", "path": "nul\x00byte"}),
        ("list_dir", {"path": "nul\x00byte"}),
    ],
)
async def test_shell_alias_rejects_newline_and_nul_arguments_as_protocol_strikes(
    tmp_path: Path,
    alias: str,
    arguments: dict,
):
    turns = [
        _turn(_call(alias, arguments, f"bad-{number}"))
        for number in range(3)
    ]
    worker, instance, _, executor, _, _, _ = await _fixture_worker(tmp_path, turns)
    recording = _record_executor(instance, executor)

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "protocol_error"
    assert recording.routes == []
    for number in range(3):
        assert _result(instance, f"bad-{number}").startswith(
            "(alias for run_command)\ninvalid tool arguments:",
        )


async def test_execute_alias_uses_trusted_pytest_but_bash_wrapper_does_not(
    tmp_path: Path,
):
    spec_test = "tests/test_calc.py::test_add"
    turns = [
        _turn(
            _call(
                "execute",
                {"command": f"pytest {spec_test}"},
                "trusted-pytest",
            ),
        ),
        _turn(
            _call(
                "bash",
                {"command": "bash -c 'pytest'"},
                "ordinary-bash",
            ),
        ),
    ]
    worker, instance, _, executor, branch, sink, _ = await _fixture_worker(
        tmp_path,
        turns,
    )
    recording = _record_executor(instance, executor)

    await instance.attempt(
        worker.WorkerBudget(max_turns=2, max_completion_tokens=100),
    )

    assert recording.routes == [
        ("pytest", spec_test),
        ("run", "bash -c 'pytest'"),
    ]
    command_receipts = [
        receipt
        for receipt in sink.receipts
        if receipt.branch_id == branch.id and receipt.kind == "command"
    ]
    assert len(command_receipts) == 2
    assert command_receipts[0].junit is not None
    assert command_receipts[0].tree_digest is not None
    assert command_receipts[1].junit is None
    assert _result(instance, "trusted-pytest").startswith(
        "(alias for run_command)\nexit 0\n",
    )
    assert _result(instance, "ordinary-bash").startswith(
        "(alias for run_command)\nexit 1\n",
    )


async def test_command_alias_without_command_is_a_bad_arguments_strike(
    tmp_path: Path,
):
    turns = [
        _turn(_call("execute", {}, f"bad-execute-{number}"))
        for number in range(3)
    ]
    worker, instance, _, executor, _, _, _ = await _fixture_worker(tmp_path, turns)
    recording = _record_executor(instance, executor)

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "protocol_error"
    assert recording.routes == []
    for number in range(3):
        assert _result(instance, f"bad-execute-{number}").startswith(
            "(alias for run_command)\ninvalid tool arguments:",
        )


async def test_browser_remains_an_unknown_tool_protocol_strike(tmp_path: Path):
    turns = [
        _turn(_call("browser", {}, f"browser-{number}"))
        for number in range(3)
    ]
    worker, instance, _, _, _, _, _ = await _fixture_worker(tmp_path, turns)

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "protocol_error"
    for number in range(3):
        assert _result(instance, f"browser-{number}") == (
            "unknown tool, the tools are read_file, edit_file, write_file, "
            "run_command, finish"
        )


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
    assert tool_names == [
        "read_file",
        "edit_file",
        "write_file",
        "run_command",
        "finish",
    ]
    assert (
        "Use read_file to inspect files (by line range for long files), "
        "edit_file to change existing files, write_file to create new files, "
        "and run_command to run tests and other commands."
    ) in first_request["messages"][0]["content"]
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
    assert branch_receipts[-1].junit is not None
    assert branch_receipts[-1].junit.n_passed == 4

    rows = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert len(rows) == 4
    assert [row["request_message_count"] for row in rows] == [2, 4, 6, 8]
    assert rows[-1]["end_reason"] == "finished"
    assert rows[-1]["usage"] == {"prompt": 10, "completion": 1, "reasoning": 0}
    assert all("finish_reason" in row for row in rows)
    assert rows[-1]["tool_calls"][0]["name"] == "finish"
    assert "api_key" not in writer.getvalue().lower()


async def test_worker_logs_provider_finish_reason(tmp_path: Path):
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(content="I need another turn.", finish_reason="length")],
    )

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    row = json.loads(writer.getvalue().splitlines()[0])
    assert row["finish_reason"] == "length"


async def test_trusted_repo_root_cd_carries_junit_but_other_cd_commands_do_not(
    tmp_path: Path,
):
    turns = [
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
        _turn(
            _call(
                "run_command",
                {"command": "cd /repo && python -m pytest -q"},
                "run-pytest",
            ),
        ),
        _turn(
            _call(
                "run_command",
                {"command": "cd tests && pytest"},
                "run-relative-cd",
            ),
        ),
        _turn(
            _call(
                "run_command",
                {"command": "cd /other && pytest"},
                "run-other-cd",
            ),
        ),
    ]
    worker, instance, _, _, branch, sink, writer = await _fixture_worker(
        tmp_path,
        turns,
        repo_root="/repo",
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=4, max_completion_tokens=100),
    )

    assert outcome.end == "budget_exhausted"
    command_receipts = [
        receipt
        for receipt in sink.receipts
        if receipt.branch_id == branch.id and receipt.kind == "command"
    ]
    assert len(command_receipts) == 3
    assert command_receipts[0].junit is not None
    assert command_receipts[0].tree_digest is not None
    assert command_receipts[1].junit is None
    assert command_receipts[2].junit is None
    rows = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert rows[1]["tool_calls"][0]["arguments"]["command"] == (
        "cd /repo && python -m pytest -q"
    )


async def test_unsupported_tool_argument_is_ignored_with_a_note(tmp_path: Path):
    turns = [
        _turn(
            _call(
                "read_file",
                {"path": "calc/__init__.py", "unsupported": True},
                "read-extra",
            ),
        ),
        _turn(
            _call(
                "write_file",
                {"path": "note.txt", "content": "continued\n"},
                "write-1",
            ),
        ),
        _turn(
            _call(
                "finish",
                {
                    "summary": "Ignored an unsupported argument and continued.",
                    "claims": _claims(changed=["note.txt"], green=False),
                },
                "finish-1",
            ),
        ),
    ]
    worker, instance, model, executor, branch, _, _ = await _fixture_worker(
        tmp_path,
        turns,
    )

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "finished"
    assert await executor.read_file(branch, "note.txt", 100) == "continued\n"
    result = next(
        message["content"]
        for message in model.requests[1]["messages"]
        if message.get("tool_call_id") == "read-extra"
    )
    assert result.splitlines()[0] == (
        "note: ignored unsupported argument(s): unsupported"
    )
    assert "def add" in result


def _large_file_repo(tmp_path: Path) -> tuple[Path, list[str]]:
    repo = make_repo(tmp_path / "source")
    lines = [f"line {number:03d} " + ("x" * 32) + "\n" for number in range(1, 601)]
    (repo / "large.txt").write_text("".join(lines))
    subprocess.run(["git", "add", "large.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "large line fixture"],
        cwd=repo,
        check=True,
    )
    return repo, lines


async def test_read_file_without_range_reports_and_continues_truncated_file(
    tmp_path: Path,
):
    repo, _ = _large_file_repo(tmp_path)
    turns = [_turn(_call("read_file", {"path": "large.txt"}, "read-large"))]
    worker, instance, _, _, _, _, _ = await _fixture_worker(
        tmp_path / "run",
        turns,
        repo=repo,
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    assert outcome.end == "budget_exhausted"
    result = next(
        message["content"]
        for message in instance.messages
        if message.get("tool_call_id") == "read-large"
    )
    assert len(result.encode()) <= 12_000
    header = result.splitlines()[0]
    match = re.fullmatch(r"\[large\.txt: lines 1-(\d+) of 600\]", header)
    assert match is not None
    last_line = int(match.group(1))
    assert 1 <= last_line < 600
    assert f"line {last_line:03d} " in result
    assert f"line {last_line + 1:03d} " not in result
    assert result.endswith(
        f"[truncated: call read_file with start_line={last_line + 1} to continue]",
    )


async def test_read_file_range_returns_only_requested_lines(tmp_path: Path):
    repo, lines = _large_file_repo(tmp_path)
    turns = [
        _turn(
            _call(
                "read_file",
                {"path": "large.txt", "start_line": 200, "end_line": 202},
                "read-range",
            ),
        ),
    ]
    worker, instance, _, _, _, _, _ = await _fixture_worker(
        tmp_path / "run",
        turns,
        repo=repo,
    )

    await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    result = next(
        message["content"]
        for message in instance.messages
        if message.get("tool_call_id") == "read-range"
    )
    assert result == (
        "[large.txt: lines 200-202 of 600]\n"
        + "".join(lines[199:202])
        + "[truncated: call read_file with start_line=203 to continue]"
    )


@pytest.mark.parametrize("view_range", [[200, 202], "[200, 202]"])
async def test_read_file_accepts_view_range_alias_without_note(
    tmp_path: Path,
    view_range: list[int] | str,
):
    repo, lines = _large_file_repo(tmp_path)
    turns = [
        _turn(
            _call(
                "read_file",
                {"path": "large.txt", "view_range": view_range},
                "read-range",
            ),
        ),
    ]
    worker, instance, _, _, _, _, _ = await _fixture_worker(
        tmp_path / "run",
        turns,
        repo=repo,
    )

    await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    result = next(
        message["content"]
        for message in instance.messages
        if message.get("tool_call_id") == "read-range"
    )
    assert not result.startswith("note:")
    assert result == (
        "[large.txt: lines 200-202 of 600]\n"
        + "".join(lines[199:202])
        + "[truncated: call read_file with start_line=203 to continue]"
    )


async def test_read_file_missing_path_returns_not_found_header(tmp_path: Path):
    turns = [_turn(_call("read_file", {"path": "missing.py"}, "read-missing"))]
    worker, instance, _, _, _, _, _ = await _fixture_worker(tmp_path, turns)

    await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    result = next(
        message["content"]
        for message in instance.messages
        if message.get("tool_call_id") == "read-missing"
    )
    assert result == "[missing.py: not found]"


async def test_edit_file_writes_only_for_one_exact_occurrence(tmp_path: Path):
    turns = [
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
                "edit-one",
            ),
        ),
        _turn(
            _call(
                "edit_file",
                {
                    "path": "calc/__init__.py",
                    "old_text": "not present",
                    "new_text": "unused",
                },
                "edit-zero",
            ),
        ),
        _turn(
            _call(
                "edit_file",
                {
                    "path": "calc/__init__.py",
                    "old_text": "def ",
                    "new_text": "function ",
                },
                "edit-two",
            ),
        ),
        _turn(
            _call(
                "finish",
                {
                    "summary": "Made one targeted edit.",
                    "claims": _claims(changed=["calc/__init__.py"], green=False),
                },
                "finish",
            ),
        ),
    ]
    worker, instance, _, executor, branch, sink, _ = await _fixture_worker(
        tmp_path,
        turns,
    )

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "finished"
    content = await executor.read_file(branch, "calc/__init__.py", 2_000_000)
    assert "return a - b" in content
    assert "function " not in content
    results = {
        message["tool_call_id"]: message["content"]
        for message in instance.messages
        if message.get("tool_call_id", "").startswith("edit-")
    }
    assert results == {
        "edit-one": "ok",
        "edit-zero": "edit refused: old_text not found",
        "edit-two": "edit refused: old_text occurs 2 times; include more context",
    }
    write_receipts = [
        receipt
        for receipt in sink.receipts
        if receipt.branch_id == branch.id and receipt.kind == "write"
    ]
    assert len(write_receipts) == 1
    assert outcome.receipt_ids == [write_receipts[0].receipt_id]


async def test_edit_file_refuses_content_at_fetch_limit_without_writing(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "source")
    original = b"target" + (b"x" * (2_000_000 - len(b"target")))
    (repo / "too-large.txt").write_bytes(original)
    subprocess.run(["git", "add", "too-large.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "large edit fixture"],
        cwd=repo,
        check=True,
    )
    turns = [
        _turn(
            _call(
                "edit_file",
                {
                    "path": "too-large.txt",
                    "old_text": "target",
                    "new_text": "changed",
                },
                "edit-large",
            ),
        ),
    ]
    worker, instance, _, executor, branch, sink, _ = await _fixture_worker(
        tmp_path / "run",
        turns,
        repo=repo,
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    result = next(
        message["content"]
        for message in instance.messages
        if message.get("tool_call_id") == "edit-large"
    )
    assert result == "edit refused: file is too large to edit safely; use run_command"
    assert (executor.workdir(branch) / "too-large.txt").read_bytes() == original
    assert not [
        receipt
        for receipt in sink.receipts
        if receipt.branch_id == branch.id and receipt.kind == "write"
    ]
    assert outcome.receipt_ids == []


async def test_edit_file_refuses_invalid_utf8_without_writing(tmp_path: Path):
    repo = make_repo(tmp_path / "source")
    original = b"before\xffafter\n"
    (repo / "invalid.txt").write_bytes(original)
    subprocess.run(["git", "add", "invalid.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "invalid utf8 edit fixture"],
        cwd=repo,
        check=True,
    )
    turns = [
        _turn(
            _call(
                "edit_file",
                {
                    "path": "invalid.txt",
                    "old_text": "before",
                    "new_text": "changed",
                },
                "edit-invalid",
            ),
        ),
    ]
    worker, instance, _, executor, branch, sink, _ = await _fixture_worker(
        tmp_path / "run",
        turns,
        repo=repo,
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    result = next(
        message["content"]
        for message in instance.messages
        if message.get("tool_call_id") == "edit-invalid"
    )
    assert result == (
        "edit refused: file is not valid UTF-8 text; use write_file or run_command"
    )
    assert (executor.workdir(branch) / "invalid.txt").read_bytes() == original
    assert not [
        receipt
        for receipt in sink.receipts
        if receipt.branch_id == branch.id and receipt.kind == "write"
    ]
    assert outcome.receipt_ids == []


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


async def test_three_consecutive_protocol_errors_end_the_attempt(tmp_path: Path):
    turns = [
        _turn(content="I will inspect the repository first."),
        _turn(_call("delete_repository", {}, "unknown-1")),
        _turn(_call("read_file", {"path": ["not", "a", "string"]}, "invalid-1")),
    ]
    worker, instance, model, _, _, _, writer = await _fixture_worker(tmp_path, turns)

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "protocol_error"
    assert outcome.claims is None
    assert outcome.turns == 3
    repair = model.requests[1]["messages"][-1]
    assert repair["role"] == "user"
    assert repair["content"] == (
        "Respond with exactly one tool call. The available tools are "
        "read_file, edit_file, write_file, run_command, finish."
    )
    invalid_result = next(
        message["content"]
        for message in instance.messages
        if message.get("tool_call_id") == "invalid-1"
    )
    assert invalid_result.startswith("invalid tool arguments:")
    rows = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert rows[0]["results"] == []
    assert rows[-1]["end_reason"] == "protocol_error"


async def test_valid_tool_call_resets_consecutive_protocol_errors(tmp_path: Path):
    turns = [
        _turn(content="I will inspect first."),
        _turn(_call("delete_repository", {}, "unknown-1")),
        _turn(_call("read_file", {"path": "calc/__init__.py"}, "read-1")),
        _turn(content="I will now edit."),
        _turn(_call("read_file", {}, "invalid-read")),
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
                    "summary": "Recovered after separated protocol errors.",
                    "claims": _claims(changed=["note.txt"], green=False),
                },
                "finish-1",
            ),
        ),
    ]
    worker, instance, model, executor, branch, _, _ = await _fixture_worker(
        tmp_path,
        turns,
    )

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "finished"
    assert outcome.turns == 7
    assert await executor.read_file(branch, "note.txt", 100) == "safe\n"
    invalid_result = next(
        message["content"]
        for message in model.requests[5]["messages"]
        if message.get("tool_call_id") == "invalid-read"
    )
    assert invalid_result.startswith("invalid tool arguments:")


async def test_worker_prompt_names_known_repository_root(tmp_path: Path):
    turns = [_turn(_call("read_file", {"path": "calc/__init__.py"}, "read-1"))]
    worker, instance, model, _, _, _, _ = await _fixture_worker(
        tmp_path,
        turns,
        repo_root="/repo",
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    assert outcome.end == "budget_exhausted"
    assert model.requests[0]["messages"][0]["content"] == (
        worker.SYSTEM_PROMPT + "Commands run in the repository root (/repo).\n"
    )


async def test_worker_prompt_names_scratch_and_can_run_a_probe_from_it(
    tmp_path: Path,
):
    scratch = str(tmp_path / "executor" / "agent1-scratch")
    turns = [
        _turn(
            _call(
                "write_file",
                {
                    "path": f"{scratch}/probe.py",
                    "content": "print('scratch probe')\n",
                },
                "write-probe",
            ),
        ),
        _turn(
            _call(
                "edit_file",
                {
                    "path": f"{scratch}/probe.py",
                    "old_text": "scratch probe",
                    "new_text": "edited scratch probe",
                },
                "edit-probe",
            ),
        ),
        _turn(
            _call(
                "run_command",
                {"command": f"python {shlex.quote(scratch + '/probe.py')}"},
                "run-probe",
            ),
        ),
        _turn(
            _call(
                "finish",
                {
                    "summary": "Ran a probe outside the repository.",
                    "claims": _claims(changed=[], green=False),
                },
                "finish",
            ),
        ),
    ]
    worker, instance, model, executor, branch, _, _ = await _fixture_worker(
        tmp_path,
        turns,
        scratch_path=scratch,
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=4, max_completion_tokens=100),
    )

    prompt = model.requests[0]["messages"][0]["content"]
    assert f"Put probe and debug scripts under the scratch path ({scratch})." in prompt
    assert (
        "New source files created in the repository ship with the fix, while test "
        "and configuration files are dropped."
    ) in prompt
    assert outcome.end == "finished"
    assert _result(instance, "write-probe") == "ok"
    assert _result(instance, "edit-probe") == "ok"
    assert "edited scratch probe" in _result(instance, "run-probe")
    assert await executor.read_file(branch, f"{scratch}/probe.py", 100) == (
        "print('edited scratch probe')\n"
    )


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
        "unknown tool, the tools are read_file, edit_file, write_file, "
        "run_command, finish"
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


def _estimated_prompt_tokens(messages: list[dict]) -> int:
    total_characters = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total_characters += len(content)
        if "tool_calls" in message:
            total_characters += len(json.dumps(message["tool_calls"]))
    return math.ceil(total_characters / 3)


def _long_guard_conversation() -> list[dict]:
    messages = [
        {"role": "system", "content": "system stays " + "s" * 30},
        {"role": "user", "content": "first user stays " + "u" * 30},
    ]
    for number, character in enumerate(("A", "B", "C"), start=1):
        call_id = f"old-{number}"
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps({"path": f"old-{number}.txt"}),
                            },
                        },
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": character * 300,
                },
            ],
        )
    messages.extend(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "protected-tool",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": "protected.txt"}),
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "protected-tool",
                "content": "P" * 300,
            },
            {"role": "assistant", "content": "recent assistant"},
            {"role": "tool", "tool_call_id": "recent-tool", "content": "R" * 300},
            {"role": "assistant", "content": "most recent assistant"},
            {"role": "user", "content": "most recent user"},
        ],
    )
    return messages


async def test_context_guard_replaces_oldest_eligible_tool_outputs_deterministically(
    tmp_path: Path,
):
    removed = "[earlier tool output removed to fit the context budget]"
    original = _long_guard_conversation()
    expected = copy.deepcopy(original)
    expected[3]["content"] = removed
    expected[5]["content"] = removed
    prompt_budget = _estimated_prompt_tokens(expected)
    observed = []

    for name in ("first", "second"):
        worker, instance, model, _, _, _, writer = await _fixture_worker(
            tmp_path / name,
            [_turn(content="no tool call")],
        )
        instance.messages = copy.deepcopy(original)

        await instance.attempt(
            worker.WorkerBudget(
                max_turns=1,
                max_completion_tokens=100,
                prompt_token_budget=prompt_budget,
            ),
        )

        request = model.requests[0]["messages"]
        row = json.loads(writer.getvalue())
        observed.append((request, row["context_guard"]))
        assert request == expected
        assert request[:2] == original[:2]
        assert request[-6:] == original[-6:]
        assert [message["role"] for message in request] == [
            message["role"] for message in original
        ]
        assert [message.get("tool_call_id") for message in request] == [
            message.get("tool_call_id") for message in original
        ]
        assert [message.get("tool_calls") for message in request] == [
            message.get("tool_calls") for message in original
        ]
        assert request[7]["content"] == original[7]["content"]
        assert row["context_guard"] == {
            "replaced_messages": 2,
            "estimated_tokens_before": _estimated_prompt_tokens(original),
            "estimated_tokens_after": _estimated_prompt_tokens(expected),
        }

    assert observed[0] == observed[1]


async def test_context_guard_leaves_under_budget_request_and_log_unchanged(
    tmp_path: Path,
):
    worker, instance, model, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(content="no tool call")],
    )
    original = copy.deepcopy(instance.messages)

    await instance.attempt(
        worker.WorkerBudget(
            max_turns=1,
            max_completion_tokens=100,
            prompt_token_budget=160_000,
        ),
    )

    assert model.requests[0]["messages"] == original
    assert "context_guard" not in json.loads(writer.getvalue())


async def test_context_guard_runs_before_appeal_model_calls(tmp_path: Path):
    removed = "[earlier tool output removed to fit the context budget]"
    worker, instance, model, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [
            _turn(content="initial response without a tool"),
            _turn(content="appeal response without a tool"),
        ],
    )
    instance.messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "first user"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "appeal-old",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": "large.txt"}),
                    },
                },
            ],
        },
        {"role": "tool", "tool_call_id": "appeal-old", "content": "X" * 900},
        {"role": "assistant", "content": "recent one"},
        {"role": "tool", "tool_call_id": "recent", "content": "short"},
        {"role": "assistant", "content": "recent two"},
        {"role": "user", "content": "recent three"},
    ]

    await instance.attempt(
        worker.WorkerBudget(
            max_turns=1,
            max_completion_tokens=100,
            prompt_token_budget=10_000,
        ),
    )
    evidence = "The target test still fails."
    projected = copy.deepcopy(instance.messages)
    projected.append(
        {
            "role": "user",
            "content": evidence + "\n\n" + worker.APPEAL_INSTRUCTION,
        },
    )
    expected = copy.deepcopy(projected)
    expected[3]["content"] = removed

    await instance.appeal(
        evidence,
        worker.WorkerBudget(
            max_turns=1,
            max_completion_tokens=100,
            prompt_token_budget=_estimated_prompt_tokens(expected),
        ),
    )

    rows = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert model.requests[0]["messages"][3]["content"] == "X" * 900
    assert model.requests[1]["messages"] == expected
    assert "context_guard" not in rows[0]
    assert rows[1]["context_guard"] == {
        "replaced_messages": 1,
        "estimated_tokens_before": _estimated_prompt_tokens(projected),
        "estimated_tokens_after": _estimated_prompt_tokens(expected),
    }


async def test_model_failure_returns_model_error(tmp_path: Path):
    worker, instance, _, _, _, _, writer = await _fixture_worker(tmp_path, [])

    outcome = await instance.attempt(worker.WorkerBudget(max_completion_tokens=100))

    assert outcome.end == "model_error"
    assert outcome.turns == 0
    assert "no scripted turn" in outcome.summary.lower()
    assert writer.getvalue() == ""


async def test_logs_ok_result_for_aliased_execute_call(tmp_path: Path):
    call = _call("execute", {"command": "printf '\u00e9'"}, "ok-alias")
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    reply = _result(instance, call.id)
    assert outcome.end == "budget_exhausted"
    assert reply == "(alias for run_command)\nexit 0\n\u00e9"
    _assert_logged_result(
        writer,
        call_id=call.id,
        name="execute",
        ran_as="run_command",
        executed=True,
        result_class="ok",
        reply=reply,
    )


async def test_logs_unknown_tool_result_without_dispatch(tmp_path: Path):
    call = _call("delete_repository", {}, "unknown-log")
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    reply = _result(instance, call.id)
    assert outcome.end == "budget_exhausted"
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as=None,
        executed=False,
        result_class="unknown_tool",
        reply=reply,
    )


async def test_logs_bad_args_result_without_dispatch(tmp_path: Path):
    call = _call("read_file", {}, "bad-args-log")
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    reply = _result(instance, call.id)
    assert outcome.end == "budget_exhausted"
    assert reply.startswith("invalid tool arguments:")
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as=None,
        executed=False,
        result_class="bad_args",
        reply=reply,
    )


async def test_logs_malformed_args_with_original_name_and_id(tmp_path: Path):
    turn = MalformedToolCall(
        content="I will inspect the repository.",
        tool_name="run_command",
        tool_call_id="malformed-log",
        raw_arguments='{"command":',
        error="invalid JSON",
        usage={"prompt": 10, "completion": 1, "reasoning": 0},
    )
    worker, instance, model, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [turn],
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    repair = instance.messages[-1]["content"]
    assert outcome.end == "budget_exhausted"
    assert model.requests[0]["messages"][-1]["content"] == (
        "Fix calc.sub and prove the repository is green."
    )
    assert repair.startswith("Respond with exactly one tool call.")
    _assert_logged_result(
        writer,
        call_id="malformed-log",
        name="run_command",
        ran_as=None,
        executed=False,
        result_class="malformed_args",
        reply=repair,
    )


async def test_logs_calls_after_first_malformed_call_in_original_order(
    tmp_path: Path,
):
    turn = MalformedToolCall(
        content=None,
        tool_name="run_command",
        tool_call_id="malformed-first",
        raw_arguments='{"command":',
        error="invalid JSON",
        raw_tool_calls=[
            {"id": "malformed-first", "name": "run_command", "malformed_args": True},
            {"id": "valid-second", "name": "read_file", "malformed_args": False},
            {"id": "malformed-third", "name": "edit_file", "malformed_args": True},
        ],
        usage={"prompt": 10, "completion": 1, "reasoning": 0},
    )
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [turn],
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    repair = instance.messages[-1]["content"]
    row = json.loads(writer.getvalue())
    assert outcome.end == "budget_exhausted"
    assert [(result["id"], result["class"]) for result in row["results"]] == [
        ("malformed-first", "malformed_args"),
        ("valid-second", "not_executed"),
        ("malformed-third", "malformed_args"),
    ]
    assert [result["result_bytes"] for result in row["results"]] == [
        len(repair.encode("utf-8")),
        0,
        0,
    ]


async def test_logs_calls_after_parsed_call_when_later_call_is_malformed(
    tmp_path: Path,
):
    first = _call("read_file", {"path": "calc/__init__.py"}, "valid-first")
    turn = MalformedToolCall(
        content=None,
        tool_calls=[first],
        tool_name="edit_file",
        tool_call_id="malformed-second",
        raw_arguments="[]",
        error="tool arguments must be a JSON object",
        raw_tool_calls=[
            {"id": "valid-first", "name": "read_file", "malformed_args": False},
            {"id": "malformed-second", "name": "edit_file", "malformed_args": True},
            {"id": "valid-third", "name": "write_file", "malformed_args": False},
        ],
        usage={"prompt": 10, "completion": 1, "reasoning": 0},
    )
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [turn],
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(max_turns=1, max_completion_tokens=100),
    )

    row = json.loads(writer.getvalue())
    assert outcome.end == "budget_exhausted"
    assert [(result["id"], result["class"]) for result in row["results"]] == [
        ("valid-first", "ok"),
        ("malformed-second", "malformed_args"),
        ("valid-third", "not_executed"),
    ]
    assert [result["result_bytes"] for result in row["results"][1:]] == [0, 0]


async def test_logs_edit_no_match_result(tmp_path: Path):
    call = _call(
        "edit_file",
        {"path": "calc/__init__.py", "old_text": "missing", "new_text": "new"},
        "edit-no-match-log",
    )
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    reply = _result(instance, call.id)
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as="edit_file",
        executed=True,
        result_class="edit_no_match",
        reply=reply,
    )


async def test_logs_edit_multiple_matches_result(tmp_path: Path):
    call = _call(
        "edit_file",
        {"path": "calc/__init__.py", "old_text": "def ", "new_text": "fn "},
        "edit-multiple-log",
    )
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    reply = _result(instance, call.id)
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as="edit_file",
        executed=True,
        result_class="edit_multiple_matches",
        reply=reply,
    )


async def test_logs_edit_too_large_result(tmp_path: Path):
    repo = make_repo(tmp_path / "source")
    (repo / "too-large.txt").write_bytes(b"target" + b"x" * 1_999_994)
    subprocess.run(["git", "add", "too-large.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "large logging fixture"],
        cwd=repo,
        check=True,
    )
    call = _call(
        "edit_file",
        {"path": "too-large.txt", "old_text": "target", "new_text": "changed"},
        "edit-too-large-log",
    )
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path / "run",
        [_turn(call)],
        repo=repo,
    )

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    reply = _result(instance, call.id)
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as="edit_file",
        executed=True,
        result_class="edit_too_large",
        reply=reply,
    )


async def test_logs_edit_invalid_utf8_result(tmp_path: Path):
    repo = make_repo(tmp_path / "source")
    (repo / "invalid.txt").write_bytes(b"before\xffafter\n")
    subprocess.run(["git", "add", "invalid.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "invalid utf8 logging fixture"],
        cwd=repo,
        check=True,
    )
    call = _call(
        "edit_file",
        {"path": "invalid.txt", "old_text": "before", "new_text": "changed"},
        "edit-invalid-utf8-log",
    )
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path / "run",
        [_turn(call)],
        repo=repo,
    )

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    reply = _result(instance, call.id)
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as="edit_file",
        executed=True,
        result_class="edit_invalid_utf8",
        reply=reply,
    )


async def test_logs_write_refused_result(tmp_path: Path):
    call = _call(
        "write_file",
        {"path": "../outside.py", "content": "unsafe\n"},
        "write-refused-log",
    )
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    reply = _result(instance, call.id)
    assert reply == "refused: path is outside the repository"
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as="write_file",
        executed=True,
        result_class="write_refused",
        reply=reply,
    )


async def test_logs_command_timeout_before_nonzero_exit(tmp_path: Path):
    call = _call(
        "run_command",
        {"command": "python -c 'import time; time.sleep(2)'"},
        "command-timeout-log",
    )
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    outcome = await instance.attempt(
        worker.WorkerBudget(
            max_turns=1,
            max_wall_seconds=1.2,
            max_completion_tokens=100,
        ),
    )

    reply = _result(instance, call.id)
    assert outcome.end == "budget_exhausted"
    assert reply.startswith("timed out")
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as="run_command",
        executed=True,
        result_class="command_timeout",
        reply=reply,
    )


async def test_logs_command_not_dispatched_when_wall_budget_is_subsecond(
    tmp_path: Path,
):
    call = _call("run_command", {"command": "printf never"}, "no-dispatch-log")
    worker, instance, _, executor, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )
    recording = _record_executor(instance, executor)

    outcome = await instance.attempt(
        worker.WorkerBudget(
            max_turns=1,
            max_wall_seconds=0.5,
            max_completion_tokens=100,
        ),
    )

    assert outcome.end == "budget_exhausted"
    assert recording.routes == []
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as=None,
        executed=False,
        result_class="command_timeout",
        reply="",
    )


async def test_logs_nonzero_exit_result(tmp_path: Path):
    call = _call("run_command", {"command": "exit 7"}, "nonzero-exit-log")
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    reply = _result(instance, call.id)
    assert reply == "exit 7"
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as="run_command",
        executed=True,
        result_class="nonzero_exit",
        reply=reply,
    )


async def test_logs_finish_refused_result(tmp_path: Path):
    call = _call(
        "finish",
        {
            "summary": "Nothing needed changing.",
            "claims": _claims(changed=[], green=False),
        },
        "finish-refused-log",
    )
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    reply = _result(instance, call.id)
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as="finish",
        executed=True,
        result_class="finish_refused",
        reply=reply,
    )


async def test_logs_noted_result_without_dispatch(tmp_path: Path):
    call = _call("think", {"thought": "Inspect first"}, "noted-log")
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    reply = _result(instance, call.id)
    assert reply == "noted"
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as=None,
        executed=False,
        result_class="noted",
        reply=reply,
    )


async def test_logs_extra_call_as_not_executed(tmp_path: Path):
    first = _call("read_file", {"path": "calc/__init__.py"}, "first-log")
    extra = _call("write_file", {"path": "extra.py", "content": "x = 1\n"}, "extra-log")
    worker, instance, _, _, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(first, extra)],
    )

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    reply = _result(instance, extra.id)
    _assert_logged_result(
        writer,
        call_id=extra.id,
        name=extra.name,
        ran_as=None,
        executed=False,
        result_class="not_executed",
        reply=reply,
    )


async def test_logs_tool_error_result_for_executor_exception(tmp_path: Path):
    call = _call("read_file", {"path": "calc/__init__.py"}, "tool-error-log")
    worker, instance, _, executor, _, _, writer = await _fixture_worker(
        tmp_path,
        [_turn(call)],
    )

    class ErrorExecutor:
        def __getattr__(self, name):
            return getattr(executor, name)

        async def read_file(self, branch, path, max_bytes):
            raise RuntimeError("read failed")

    instance.executor = ErrorExecutor()

    await instance.attempt(worker.WorkerBudget(max_turns=1, max_completion_tokens=100))

    reply = _result(instance, call.id)
    assert reply == "tool error: RuntimeError: read failed"
    _assert_logged_result(
        writer,
        call_id=call.id,
        name=call.name,
        ran_as="read_file",
        executed=True,
        result_class="tool_error",
        reply=reply,
    )
