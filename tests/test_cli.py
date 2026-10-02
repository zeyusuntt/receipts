from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from receipts.agent.planner import Plan
from receipts.agent.worker import WorkerOutcome
from receipts.cli import _parser, main
from receipts.llm import AssistantTurn, FakeModel, ToolCall
from receipts.models import (
    Baseline,
    Checkpoint,
    Claims,
    JunitSummary,
    PredicateResult,
    Verdict,
)
from receipts.orchestrate import (
    AttemptResult,
    Disclosure,
    RunBudgets,
    RunInput,
    RunResult,
)
from receipts.sandbox.protocol import ImageSource
from receipts.swerebench import Instance
from tests.fixtures.repo_factory import make_repo


TARGET = "tests/test_calc.py::test_sub"
FIXED_CALC = '''def add(a, b):
    return a + b


def sub(a, b):
    return a - b
'''


def _call(name: str, arguments: dict, call_id: str) -> ToolCall:
    return ToolCall(name=name, arguments=arguments, id=call_id)


def _turn(call: ToolCall) -> AssistantTurn:
    return AssistantTurn(
        content=None,
        tool_calls=[call],
        usage={"prompt": 10, "completion": 2, "reasoning": 0},
    )


def _honest_model() -> FakeModel:
    claims = {
        "tests_run": True,
        "target_tests_pass": True,
        "full_suite_pass": True,
        "files_changed": ["calc/__init__.py"],
    }
    return FakeModel(
        json_objects=[
            {
                "hypothesis": "calc.sub adds instead of subtracting",
                "files_to_edit": ["calc/__init__.py"],
                "approach": "Change calc.sub to subtract and run the suite.",
            },
        ],
        turns=[
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
            _turn(
                _call(
                    "finish",
                    {"summary": "Fixed subtraction and ran the suite.", "claims": claims},
                    "finish",
                ),
            ),
        ],
    )


def _sample_result() -> RunResult:
    passing = JunitSummary(
        passed=["tests/test_calc.py::test_add"],
        failed=[TARGET],
        errors=[],
        skipped=[],
    )
    baseline = Baseline(
        runs=[passing, passing],
        run_receipt_ids=["base-1", "base-2"],
        collected_ids=["tests/test_calc.py::test_add", TARGET],
        skipped_ids=[],
        protected=["tests/test_calc.py::test_add"],
        unstable=[],
        target=[TARGET],
    )
    predicates = [
        PredicateResult(
            id="R1_fail_to_pass",
            passed=True,
            evidence=f"target tests passed: {TARGET}",
        ),
        PredicateResult(
            id="R2_pass_to_pass",
            passed=True,
            evidence="1 baseline-passing tests still pass",
        ),
        PredicateResult(
            id="R3_no_shrink",
            passed=True,
            evidence="all 2 baseline tests collected; skips unchanged (0)",
        ),
        PredicateResult(
            id="R4_patch_scope",
            passed=True,
            evidence="patch touches 1 file(s), all in scope",
        ),
        PredicateResult(
            id="R5_provenance",
            passed=True,
            evidence="agent and witness chains are unbroken; applied digest matches",
        ),
        PredicateResult(
            id="R6_claim_audit",
            passed=True,
            evidence="claimed green; own last run: 2 passed, 0 failed",
        ),
    ]
    verdict = Verdict(
        branch_id="agent1",
        status="PASS",
        predicates=predicates,
        claim_audit="honest",
        claim_evidence="claimed green; own last run: 2 passed, 0 failed",
    )
    claims = Claims(
        tests_run=True,
        target_tests_pass=True,
        full_suite_pass=True,
        files_changed=["src/calc.py"],
    )
    worker = WorkerOutcome(
        end="finished",
        claims=claims,
        summary="Corrected subtraction.",
        turns=3,
        receipt_ids=["agent1-1", "agent1-2"],
    )
    run_input = RunInput(
        source={"url": "/repo", "commit": "abc123", "install_cmd": "true"},
        issue="Subtraction is incorrect.",
        spec_tests=[TARGET],
        suite_scope="tests",
        appeals=1,
        budgets=RunBudgets(),
    )
    disclosure = Disclosure(
        model={
            "client": "FakeModel",
            "model": "fake-model",
            "temperature": 1.0,
            "top_p": 0.95,
            "thinking": False,
        },
        receipts_version="0.0.1",
        executor_kind="local",
        test_digests={"tests/test_calc.py": "test-digest"},
        pytest_config_digests={"pyproject.toml": "config-digest"},
        lock_sha256="lock-digest",
    )
    attempt = AttemptResult(
        number=1,
        worker=worker,
        verdict=verdict,
        patch_path="attempts/1/patch.diff",
        filtered_patch_path="attempts/1/filtered.diff",
        witness_branch_id="w1",
        dropped_paths=["tests/test_calc.py"],
    )
    return RunResult(
        input=run_input,
        baseline=baseline,
        plan=Plan(
            hypothesis="The subtraction operator is wrong.",
            files_to_edit=["src/calc.py"],
            approach="Replace addition with subtraction.",
        ),
        attempts=[attempt],
        final_verdict=verdict,
        verdict_history=[verdict],
        selected_patch_path="attempts/1/filtered.diff",
        verified_fix=True,
        cost={
            "models": {
                "fake-model": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "reasoning_tokens": 0,
                    "estimated_dollars": 0.01,
                },
            },
            "estimated_dollars": 0.01,
            "sandbox_seconds": 1.25,
            "pricing_is_estimate": True,
        },
        wall_time_s=2.5,
        disclosure=disclosure,
        snapshot_receipt_id="base-5",
        checkpoint=Checkpoint(
            id="checkpoint-1",
            parent="base-image",
            digest="checkpoint-digest",
        ),
        checkpoint_id="checkpoint-1",
        agent_branch_id="agent1",
    )


def test_fix_runs_offline_with_fake_model_and_local_executor(
    tmp_path: Path,
    capsys,
):
    repo = make_repo(tmp_path / "source")
    issue_file = tmp_path / "issue.txt"
    issue_file.write_text("calc.sub(5, 3) must return 2\n", encoding="utf-8")
    run_dir = tmp_path / "run"

    status = main(
        [
            "fix",
            "--repo",
            str(repo),
            "--commit",
            "HEAD",
            "--test",
            TARGET,
            "--issue-file",
            str(issue_file),
            "--install",
            "true",
            "--suite",
            "tests",
            "--executor",
            "local",
            "--out",
            str(run_dir),
        ],
        model=_honest_model(),
    )

    output = capsys.readouterr().out
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert status == 0
    assert result["final_verdict"]["status"] == "PASS"
    assert "**Verdict: VERIFIED**" in output
    assert TARGET in output


def test_fix_builds_daytona_executor_for_an_image_source(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    import receipts.cli as cli

    issue_file = tmp_path / "issue.txt"
    issue_file.write_text("Repair the formatter.\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    captured = {}

    class FakeDaytonaClient:
        def __init__(self, config):
            captured["config"] = config

    class FakeDaytonaExecutor:
        def __init__(self, root, sink, run_id, api):
            captured["executor"] = self
            captured["root"] = root
            captured["sink"] = sink
            captured["run_id"] = run_id
            captured["api"] = api
            self.closed = False

        async def close(self):
            self.closed = True

    async def fake_fix(executor, model, source, issue, tests, suite, out, *, budgets):
        captured["source"] = source
        captured["issue"] = issue
        captured["tests"] = tests
        captured["suite"] = suite
        captured["out"] = out
        captured["budgets"] = budgets
        return _sample_result()

    monkeypatch.setenv("DAYTONA_API_KEY", "test-daytona-key")
    monkeypatch.setattr(cli, "AsyncDaytona", FakeDaytonaClient)
    monkeypatch.setattr(cli, "DaytonaExecutor", FakeDaytonaExecutor)
    monkeypatch.setattr(cli, "fix", fake_fix)

    status = main(
        [
            "fix",
            "--image",
            "swerebench/example:1",
            "--workdir",
            "/example",
            "--python",
            "python3",
            "--test",
            TARGET,
            "--issue-file",
            str(issue_file),
            "--suite",
            "tests/test_calc.py",
            "--executor",
            "daytona",
            "--out",
            str(run_dir),
        ],
        model=_honest_model(),
    )

    assert status == 0
    assert captured["config"].api_key == "test-daytona-key"
    assert captured["source"] == ImageSource(
        image="swerebench/example:1",
        workdir="/example",
        python="python3",
    )
    assert captured["issue"] == "Repair the formatter."
    assert captured["tests"] == [TARGET]
    assert captured["suite"] == "tests/test_calc.py"
    assert captured["out"] == run_dir
    assert captured["budgets"].worker.max_turns == 60
    assert captured["budgets"].worker.max_wall_seconds == 1_500
    assert captured["budgets"].worker.max_completion_tokens == 96_000
    assert captured["budgets"].worker.prompt_token_budget == 160_000
    assert captured["executor"].closed is True
    assert "**Verdict: VERIFIED**" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "fix",
            "--image",
            "swerebenchv2/example:1",
            "--workdir",
            "/repo",
            "--test",
            TARGET,
            "--issue-file",
            "issue.txt",
            "--executor",
            "tokenfactory",
            "--out",
            "run",
        ],
        [
            "pilot",
            "run",
            "--candidates",
            "candidates.txt",
            "--rows",
            "rows.jsonl",
            "--executor",
            "tokenfactory",
            "--out",
            "pilot",
        ],
        [
            "pilot",
            "screen",
            "--candidates",
            "candidates.txt",
            "--start",
            "1",
            "--exclude",
            "exclude.txt",
            "--want",
            "1",
            "--executor",
            "tokenfactory",
            "--out",
            "screen.jsonl",
        ],
    ],
)
def test_tokenfactory_executor_parses_for_fix_and_pilot_commands(arguments):
    assert _parser().parse_args(arguments).executor == "tokenfactory"


def test_fix_selects_tokenfactory_executor_and_closes_one_api_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import receipts.cli as cli

    issue_file = tmp_path / "issue.txt"
    issue_file.write_text("Repair the formatter.\n", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeApi:
        def __init__(self) -> None:
            self.close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1

    api = FakeApi()

    class FakeApiType:
        @classmethod
        def from_env(cls):
            captured["from_env_calls"] = int(captured.get("from_env_calls", 0)) + 1
            return api

    class FakeExecutor:
        def __init__(self, root, sink, run_id, selected_api, *, busybox):
            captured.update(
                executor=self,
                root=root,
                sink=sink,
                run_id=run_id,
                api=selected_api,
                busybox=busybox,
            )
            self.closed = False

        async def close(self):
            self.closed = True

    async def fake_fix(executor, model, source, issue, tests, suite, out, *, budgets):
        captured.update(source=source, issue=issue, tests=tests, suite=suite, out=out)
        return _sample_result()

    monkeypatch.setattr(cli, "TokenFactorySandboxApi", FakeApiType)
    monkeypatch.setattr(cli, "TokenFactoryExecutor", FakeExecutor)
    monkeypatch.setattr(cli, "load_busybox", lambda: b"trusted-busybox")
    monkeypatch.setattr(cli, "fix", fake_fix)

    status = main(
        [
            "fix",
            "--image",
            "swerebenchv2/example:1",
            "--workdir",
            "/repo",
            "--test",
            TARGET,
            "--issue-file",
            str(issue_file),
            "--executor",
            "tokenfactory",
            "--out",
            str(tmp_path / "run"),
        ],
        model=_honest_model(),
    )

    assert status == 0
    assert captured["from_env_calls"] == 1
    assert captured["api"] is api
    assert captured["busybox"] == b"trusted-busybox"
    assert captured["source"] == ImageSource(
        image="swerebenchv2/example:1",
        workdir="/repo",
        python="python",
    )
    assert captured["executor"].closed is True
    assert api.close_calls == 1


def test_show_prints_the_serialized_run_receipt(tmp_path: Path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "result.json").write_text(
        _sample_result().model_dump_json(),
        encoding="utf-8",
    )

    status = main(["show", str(run_dir)])

    output = capsys.readouterr().out
    assert status == 0
    assert "**Verdict: VERIFIED**" in output
    assert TARGET in output
    assert "Corrected subtraction." in output
    assert "src/calc.py" in output
    assert "tests/test_calc.py" in output
    assert "test-digest" in output
    assert "lock-digest" in output
    assert "fake-model" in output
    assert "checkpoint-1" in output
    assert "$0.010000" in output


def test_doctor_without_live_reports_ready_for_complete_dotenv(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=secret\n"
        "OPENAI_BASE_URL=https://example.invalid/v1/\n"
        "NEMOTRON_MODEL=fake-model\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    status = main(["doctor"])

    assert status == 0
    assert capsys.readouterr().out == "READY\n"


def test_doctor_reports_the_first_missing_dotenv_value(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    (tmp_path / ".env").write_text(
        "OPENAI_BASE_URL=https://example.invalid/v1/\n"
        "NEMOTRON_MODEL=fake-model\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    status = main(["doctor"])

    assert status == 1
    assert capsys.readouterr().out == "MISSING OPENAI_API_KEY\n"


def test_preflight_subcommand_parses_optional_output_path(tmp_path: Path):
    output_path = tmp_path / "preflight.json"

    default_args = _parser().parse_args(["preflight"])
    custom_args = _parser().parse_args(["preflight", "--out", str(output_path)])

    assert default_args.command == "preflight"
    assert default_args.out is None
    assert default_args.executor == "daytona"
    assert custom_args.command == "preflight"
    assert custom_args.out == output_path

    tokenfactory_args = _parser().parse_args(
        ["preflight", "--executor", "tokenfactory"],
    )
    assert tokenfactory_args.executor == "tokenfactory"


def test_pilot_screen_arguments_parse(tmp_path: Path):
    candidates = tmp_path / "candidates.txt"
    exclusions = tmp_path / "exclude.txt"
    output = tmp_path / "screen.jsonl"

    args = _parser().parse_args(
        [
            "pilot",
            "screen",
            "--candidates",
            str(candidates),
            "--start",
            "59",
            "--exclude",
            str(exclusions),
            "--want",
            "110",
            "--out",
            str(output),
            "--concurrency",
            "2",
        ],
    )

    assert args.command == "pilot"
    assert args.pilot_command == "screen"
    assert args.candidates == candidates
    assert args.start == 59
    assert args.exclude == exclusions
    assert args.want == 110
    assert args.out == output
    assert args.concurrency == 2


def test_pilot_watch_arguments_parse(tmp_path: Path):
    pilot_dir = tmp_path / "pilot"

    args = _parser().parse_args(
        [
            "pilot",
            "watch",
            str(pilot_dir),
            "4321",
            "--interval",
            "0.25",
            "--model-budget-usd",
            "45",
        ],
    )

    assert args.command == "pilot"
    assert args.pilot_command == "watch"
    assert args.pilot_dir == pilot_dir
    assert args.pid == 4321
    assert args.interval == 0.25
    assert args.model_budget_usd == 45.0


async def test_pilot_signal_handler_cancels_running_task():
    import receipts.cli as cli

    task = asyncio.create_task(asyncio.Event().wait())
    cli._cancel_task(task)

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize("failure", [None, "release", "close"])
async def test_screen_executor_finishes_full_cleanup_when_release_is_cancelled(
    failure: str | None,
):
    import receipts.cli as cli

    release_started = asyncio.Event()
    allow_release = asyncio.Event()

    class Executor:
        def __init__(self) -> None:
            self.released = False
            self.closed = False
            self.usage_calls = 0

        async def release(self, branch) -> None:
            release_started.set()
            await allow_release.wait()
            self.released = True
            if failure == "release":
                raise RuntimeError("release failed")

        async def close(self) -> None:
            await asyncio.sleep(0)
            self.closed = True
            if failure == "close":
                raise RuntimeError("close failed")

        def sandbox_usage(self) -> list[dict]:
            self.usage_calls += 1
            return [{"sandbox_id": "screen-1"}]

    executor = Executor()
    protected = cli._ScreenCleanupExecutor(executor)
    task = asyncio.create_task(protected.release(object()))
    await release_started.wait()
    cli._cancel_task(task)
    await asyncio.sleep(0)
    allow_release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert executor.released is True
    assert executor.closed is True
    assert executor.usage_calls == 1
    assert protected.sandbox_usage() == [{"sandbox_id": "screen-1"}]


def test_pilot_cleanup_arguments_parse(tmp_path: Path):
    root = tmp_path / "pilot"

    dry_run = _parser().parse_args(["pilot", "cleanup", "--root", str(root)])
    confirmed = _parser().parse_args(
        ["pilot", "cleanup", "--root", str(root), "--yes"],
    )

    assert dry_run.command == "pilot"
    assert dry_run.pilot_command == "cleanup"
    assert dry_run.root == root
    assert dry_run.yes is False
    assert confirmed.yes is True


def test_pilot_replay_arguments_parse(tmp_path: Path):
    launch_3 = tmp_path / "launch-3"
    launch_2 = tmp_path / "launch-2"
    data_path = tmp_path / "rows.jsonl"
    output_prefix = tmp_path / "replay"

    args = _parser().parse_args(
        [
            "pilot",
            "replay",
            str(launch_3),
            str(launch_2),
            "--data",
            str(data_path),
            "--out",
            str(output_prefix),
        ],
    )

    assert args.command == "pilot"
    assert args.pilot_command == "replay"
    assert args.run_dirs == [launch_3, launch_2]
    assert args.data == data_path
    assert args.out == output_prefix


def test_pilot_screen_never_constructs_a_model(tmp_path: Path, monkeypatch, capsys):
    import receipts.cli as cli

    candidates_path = tmp_path / "candidates.txt"
    exclusions_path = tmp_path / "exclude.txt"
    output = tmp_path / "screen.jsonl"
    candidates_path.write_text("candidate-1 metadata\n", encoding="utf-8")
    exclusions_path.write_text("# none\n", encoding="utf-8")
    candidate = Instance(
        instance_id="candidate-1",
        repo="fixture/calc",
        base_commit="HEAD",
        image_name="fixture/calc:latest",
        test_patch="",
        fail_to_pass=[TARGET],
        pass_to_pass=[],
        test_cmd="pytest tests -rA",
        problem_statement="Fix subtraction.",
    )
    captured = {}

    def fail_model(*args, **kwargs):
        raise AssertionError("screening must not construct a model")

    async def fake_screen(
        make_executor,
        candidates,
        ledger_path,
        *,
        start,
        exclude,
        want,
        concurrency,
    ):
        captured.update(
            candidates=candidates,
            ledger_path=ledger_path,
            start=start,
            exclude=exclude,
            want=want,
            concurrency=concurrency,
        )
        return ["candidate-1"]

    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    monkeypatch.setattr(cli, "TokenFactoryClient", fail_model)
    monkeypatch.setattr(cli, "_load_pilot_candidates", lambda *args: [candidate])
    monkeypatch.setattr(cli, "screen_candidates", fake_screen, raising=False)

    status = main(
        [
            "pilot",
            "screen",
            "--candidates",
            str(candidates_path),
            "--start",
            "1",
            "--exclude",
            str(exclusions_path),
            "--want",
            "1",
            "--out",
            str(output),
        ],
    )

    assert status == 0
    assert captured["candidates"] == [candidate]
    assert captured["ledger_path"] == output
    assert captured["start"] == 1
    assert captured["exclude"] == set()
    assert captured["want"] == 1
    assert captured["concurrency"] == 1
    assert capsys.readouterr().out == "SCREEN included=1\n"


@pytest.mark.parametrize("command", ["run", "screen"])
def test_pilot_commands_select_tokenfactory_factory_with_shared_inputs(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import receipts.cli as cli

    candidate = Instance(
        instance_id="candidate-1",
        repo="fixture/calc",
        base_commit="HEAD",
        image_name="fixture/calc:latest",
        test_patch="",
        fail_to_pass=[TARGET],
        pass_to_pass=[],
        test_cmd="pytest tests -rA",
        problem_statement="Fix subtraction.",
    )
    captured: dict[str, object] = {}

    class FakeApi:
        def __init__(self) -> None:
            self.close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1

    api = FakeApi()

    class FakeApiType:
        @classmethod
        def from_env(cls):
            captured["from_env_calls"] = int(captured.get("from_env_calls", 0)) + 1
            return api

    def fake_factory(executor_root, selected_api, busybox, *, shield_cleanup=False):
        captured.update(
            executor_root=executor_root,
            api=selected_api,
            busybox=busybox,
            shield_cleanup=shield_cleanup,
        )
        return lambda run_id: (run_id, selected_api, busybox)

    async def fake_run_pilot(
        make_executor,
        model,
        candidates,
        pilot_dir,
        *,
        n,
        concurrency,
        budgets,
    ):
        captured["made"] = make_executor("pilot-run")
        captured["concurrency"] = concurrency
        return []

    async def fake_screen(
        make_executor,
        candidates,
        ledger_path,
        *,
        start,
        exclude,
        want,
        concurrency,
    ):
        captured["made"] = make_executor("screen-run")
        captured["concurrency"] = concurrency
        return []

    monkeypatch.setattr(cli, "TokenFactorySandboxApi", FakeApiType)
    monkeypatch.setattr(cli, "load_busybox", lambda: b"trusted-busybox")
    monkeypatch.setattr(cli, "_tokenfactory_executor_factory", fake_factory, raising=False)
    monkeypatch.setattr(cli, "_load_pilot_candidates", lambda *args: [candidate])
    monkeypatch.setattr(cli, "run_pilot", fake_run_pilot)
    monkeypatch.setattr(cli, "screen_candidates", fake_screen)

    if command == "run":
        arguments = [
            "pilot",
            "run",
            "--candidates",
            str(tmp_path / "candidates.txt"),
            "--rows",
            str(tmp_path / "rows.jsonl"),
            "--executor",
            "tokenfactory",
            "--out",
            str(tmp_path / "pilot"),
            "--concurrency",
            "2",
        ]
        status = main(arguments, model=FakeModel())
        expected_run_id = "pilot-run"
    else:
        exclusions = tmp_path / "exclude.txt"
        exclusions.write_text("# none\n", encoding="utf-8")
        arguments = [
            "pilot",
            "screen",
            "--candidates",
            str(tmp_path / "candidates.txt"),
            "--start",
            "1",
            "--exclude",
            str(exclusions),
            "--want",
            "1",
            "--executor",
            "tokenfactory",
            "--out",
            str(tmp_path / "screen.jsonl"),
            "--concurrency",
            "2",
        ]
        status = main(arguments)
        expected_run_id = "screen-run"

    assert status == 0
    assert captured["from_env_calls"] == 1
    assert captured["api"] is api
    assert captured["busybox"] == b"trusted-busybox"
    assert captured["shield_cleanup"] is (command == "screen")
    assert captured["made"] == (expected_run_id, api, b"trusted-busybox")
    assert captured["concurrency"] == 2
    assert api.close_calls == 1


async def test_tokenfactory_factory_borrows_shared_api_until_invocation_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import receipts.cli as cli

    constructed_with: list[object] = []

    class FakeApi:
        def __init__(self) -> None:
            self.close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1

    class FakeExecutor:
        def __init__(self, root, sink, run_id, api, *, busybox):
            self.root = root
            self.api = api
            self.busybox = busybox
            constructed_with.append(api)

        async def close(self) -> None:
            await self.api.aclose()

    api = FakeApi()
    monkeypatch.setattr(cli, "TokenFactoryExecutor", FakeExecutor)
    make_executor = cli._tokenfactory_executor_factory(
        tmp_path,
        api,
        b"trusted-busybox",
    )

    first = make_executor("first")
    second = make_executor("second")
    await first.close()
    await second.close()

    assert constructed_with == [api, api]
    assert first.root == tmp_path / "first"
    assert second.root == tmp_path / "second"
    assert first.busybox == second.busybox == b"trusted-busybox"
    assert api.close_calls == 0
    await api.aclose()
    assert api.close_calls == 1
