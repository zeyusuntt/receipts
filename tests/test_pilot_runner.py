from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from receipts.agent.worker import WorkerBudget
from receipts.llm import AssistantTurn, FakeModel, ToolCall
from receipts.models import Branch, JunitSummary, Receipt, Verdict
from receipts.orchestrate import RunBudgets
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import ImageSource, RepoAtCommit
from receipts.sandbox.sink import MemorySink
from receipts.swerebench import Instance, OfficialJudgement
from tests.fixtures.repo_factory import make_repo


TARGET = "tests/test_calc.py::test_sub"
PROTECTED = "tests/test_calc.py::test_add"
FIXED_CALC = '''def add(a, b):
    return a + b


def sub(a, b):
    return a - b
'''
ONLY_PASSING_TARGET = '''def test_sub():
    assert True
'''


def _runner_module():
    try:
        return importlib.import_module("receipts.pilot.runner")
    except ModuleNotFoundError:
        pytest.fail("receipts.pilot.runner is missing")


def _call(name: str, arguments: dict, call_id: str) -> ToolCall:
    return ToolCall(name=name, arguments=arguments, id=call_id)


def _turn(name: str, arguments: dict, call_id: str) -> AssistantTurn:
    return AssistantTurn(
        content=None,
        tool_calls=[_call(name, arguments, call_id)],
        usage={"prompt": 10, "completion": 2, "reasoning": 0},
    )


def _finish(call_id: str, changed: list[str]) -> AssistantTurn:
    return _turn(
        "finish",
        {
            "summary": "Finished the requested repair and ran the tests.",
            "claims": {
                "tests_run": True,
                "target_tests_pass": True,
                "full_suite_pass": True,
                "files_changed": changed,
            },
        },
        call_id,
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


def _instance(instance_id: str, *, target: str = TARGET) -> Instance:
    return Instance(
        instance_id=instance_id,
        repo="fixture/calc",
        base_commit="HEAD",
        image_name="fixture/calc:latest",
        test_patch="",
        fail_to_pass=[target],
        pass_to_pass=[PROTECTED] if target != PROTECTED else [],
        test_cmd="pytest -rA tests",
        problem_statement="Fix subtraction without breaking addition.",
    )


def _budgets() -> RunBudgets:
    return RunBudgets(
        baseline_limit_s=60,
        verification_timeout_s=60,
        worker=WorkerBudget(
            max_turns=12,
            max_wall_seconds=60,
            max_completion_tokens=100,
            prompt_token_budget=123_456,
        ),
    )


def _pilot_record(
    runner,
    instance_id: str,
    status: str,
    run_dir: Path,
    reason: str | None = None,
):
    return runner.InstanceRecord(
        instance_id=instance_id,
        status=status,
        reason=reason,
        run_dir=str(run_dir),
        attempts=[],
        final=None,
        cost=runner.PilotCost(
            tokens=0,
            model_dollars=None,
            sandbox_lifetime_seconds=0,
            sandbox_dollars_estimate=0,
        ),
        wall_time_s=0,
    )


def _persist_record(pilot_dir: Path, record) -> None:
    record_path = pilot_dir / record.instance_id / "record.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    Path(record.run_dir).mkdir(parents=True, exist_ok=True)
    record_path.write_text(record.model_dump_json(), encoding="utf-8")


class _ImageLocalExecutor:
    def __init__(
        self,
        root: Path,
        repo: Path,
        run_id: str,
        *,
        fail_official_apply: bool = False,
    ) -> None:
        self.inner = LocalExecutor(root, MemorySink(), run_id)
        self.repo = repo
        self.fail_official_apply = fail_official_apply
        self.closed = False

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

    async def apply_patch(self, branch, patch_text):
        if self.fail_official_apply and branch.id.startswith("official"):
            patch_text = "not a patch\n"
        return await self.inner.apply_patch(branch, patch_text)

    async def close(self) -> None:
        self.closed = True
        if self.inner.root.exists():
            shutil.rmtree(self.inner.root)

    def sandbox_usage(self) -> list[dict]:
        return [
            {
                "sandbox_id": "sandbox-a",
                "seconds": 3_600.0,
                "resources": {"cpu": 2, "memory": 2, "disk": 5},
            },
            {
                "sandbox_id": "sandbox-b",
                "seconds": 1_800.0,
                "resources": {"cpu": 4, "memory": 8, "disk": 10},
            },
        ]


def _executor_factory(
    tmp_path: Path,
    repo: Path,
    created: list[_ImageLocalExecutor],
    *,
    fail_official_apply: bool = False,
):
    def make_executor(run_id: str) -> _ImageLocalExecutor:
        executor = _ImageLocalExecutor(
            tmp_path / "executors" / run_id,
            repo,
            run_id,
            fail_official_apply=fail_official_apply,
        )
        created.append(executor)
        return executor

    return make_executor


async def test_honest_agent_writes_atomic_ran_record_with_official_agreement(
    tmp_path: Path,
):
    runner = _runner_module()
    repo = make_repo(tmp_path / "source")
    created: list[_ImageLocalExecutor] = []
    model = _model(
        [
            _turn(
                "write_file",
                {"path": "calc/__init__.py", "content": FIXED_CALC},
                "write-source",
            ),
            _turn("run_command", {"command": "python -m pytest -q"}, "run-suite"),
            _finish("finish", ["calc/__init__.py"]),
        ],
    )

    instance = _instance("fixture__calc-honest")
    instance.test_patch = """diff --git a/config/fixture.yaml b/config/fixture.yaml
new file mode 100644
--- /dev/null
+++ b/config/fixture.yaml
@@ -0,0 +1 @@
+enabled: true
"""
    record = await runner.run_instance(
        _executor_factory(tmp_path, repo, created),
        model,
        instance,
        tmp_path / "pilot",
        _budgets(),
    )

    assert record.status == "ran"
    assert record.reason is None
    assert len(record.attempts) == 1
    attempt = record.attempts[0]
    assert attempt.end == "finished"
    assert attempt.claimed_done is True
    assert attempt.naive_green is True
    assert attempt.gate_status == "PASS"
    assert attempt.failed_predicate_ids == []
    assert attempt.claim_audit == "honest"
    assert attempt.official_resolved is True
    assert attempt.agreement == "agree_pass"
    assert attempt.filtered_patch_sha256 == hashlib.sha256(
        (Path(record.run_dir) / "attempts/1/filtered.diff").read_bytes(),
    ).hexdigest()
    assert attempt.filtered_sha256 == attempt.filtered_patch_sha256
    assert attempt.witness_apply_sha256 == attempt.filtered_sha256
    assert attempt.official.applied_sha256 == attempt.filtered_sha256
    assert record.final.gate_status == "PASS"
    assert record.final.verified_fix is True
    assert record.final.official_resolved is True
    assert record.cost.tokens == 36
    assert record.cost.model_dollars is None
    assert record.cost.sandbox_lifetime_seconds == 5_400.0
    assert record.cost.sandbox_dollars_estimate == pytest.approx(0.29907)
    assert record.wall_time_s > 0
    assert created[0].closed is True
    run_input = json.loads(
        (Path(record.run_dir) / "input.json").read_text(encoding="utf-8"),
    )
    assert run_input["spec_paths"] == [
        "config/fixture.yaml",
        "tests/test_calc.py",
    ]
    assert run_input["budgets"]["worker"]["prompt_token_budget"] == 123_456

    record_path = tmp_path / "pilot" / record.instance_id / "record.json"
    assert json.loads(record_path.read_text(encoding="utf-8")) == record.model_dump(
        mode="json",
    )
    assert not record_path.with_suffix(".json.tmp").exists()
    branch_receipts = list(Path(record.run_dir).glob("branches/*/receipts.jsonl"))
    assert {path.parent.name for path in branch_receipts} >= {
        "base",
        "agent1",
        "w1",
        "official1",
    }
    persisted_log_paths = []
    persisted_patch_paths = []
    for receipt_path in branch_receipts:
        for line in receipt_path.read_text(encoding="utf-8").splitlines():
            receipt = json.loads(line)
            if receipt["log_path"] is not None:
                persisted_log_paths.append(Path(receipt["log_path"]))
            if receipt["diff"] is not None and receipt["diff"]["patch_path"] is not None:
                persisted_patch_paths.append(Path(receipt["diff"]["patch_path"]))
    assert persisted_log_paths
    assert all(path.is_relative_to(Path(record.run_dir)) for path in persisted_log_paths)
    assert all(path.is_file() for path in persisted_log_paths)
    assert persisted_patch_paths
    assert all(path.is_relative_to(Path(record.run_dir)) for path in persisted_patch_paths)
    assert all(path.is_file() for path in persisted_patch_paths)
    official_records = json.loads(
        (Path(record.run_dir) / "official/records.json").read_text(encoding="utf-8"),
    )
    assert official_records[0]["log_sha256"] == attempt.official.log_sha256


def test_daytona_price_constants_record_published_rates_and_read_date():
    import receipts.cost as cost

    assert cost.DAYTONA_PRICING_READ_DATE == "2026-10-01"
    assert cost.DAYTONA_VCPU_DOLLARS_PER_HOUR == 0.0504
    assert cost.DAYTONA_MEMORY_GIB_DOLLARS_PER_HOUR == 0.0162
    assert cost.DAYTONA_DISK_GIB_DOLLARS_PER_HOUR == 0.000108
    assert cost.DAYTONA_INCLUDED_DISK_GIB == 5


async def test_test_edit_is_rejected_but_naive_green_is_recorded(tmp_path: Path):
    runner = _runner_module()
    repo = make_repo(tmp_path / "source")
    created: list[_ImageLocalExecutor] = []
    model = _model(
        [
            _turn(
                "write_file",
                {"path": "tests/test_calc.py", "content": ONLY_PASSING_TARGET},
                "write-test",
            ),
            _turn("run_command", {"command": "pytest -q"}, "run-suite"),
            _finish("finish", ["tests/test_calc.py"]),
        ],
    )

    record = await runner.run_instance(
        _executor_factory(tmp_path, repo, created),
        model,
        _instance("fixture__calc-test-edit"),
        tmp_path / "pilot",
        _budgets(),
    )

    assert record.status == "ran"
    assert len(record.attempts) == 2
    first = record.attempts[0]
    assert first.claimed_done is True
    assert first.naive_green is True
    assert first.gate_status == "REJECTED"
    assert "R4_patch_scope" in first.failed_predicate_ids
    assert first.official_resolved is False
    assert first.agreement == "agree_fail"
    assert created[0].closed is True


async def test_naive_green_uses_latest_pytest_even_when_it_has_no_junit(tmp_path: Path):
    runner = _runner_module()
    repo = make_repo(tmp_path / "source")
    created: list[_ImageLocalExecutor] = []
    model = _model(
        [
            _turn(
                "write_file",
                {"path": "calc/__init__.py", "content": FIXED_CALC},
                "write-source",
            ),
            _turn("run_command", {"command": "pytest -q"}, "run-green"),
            _turn(
                "run_command",
                {"command": "pytest --not-a-real-pytest-flag"},
                "run-invalid",
            ),
            _finish("finish", ["calc/__init__.py"]),
        ],
    )

    record = await runner.run_instance(
        _executor_factory(tmp_path, repo, created),
        model,
        _instance("fixture__calc-last-pytest-invalid"),
        tmp_path / "pilot",
        _budgets(),
    )

    assert record.status == "ran"
    assert record.attempts[0].naive_green is False


async def test_gate_pass_without_official_resolution_is_not_a_verified_fix(
    tmp_path: Path,
):
    runner = _runner_module()
    repo = make_repo(tmp_path / "source")
    created: list[_ImageLocalExecutor] = []
    model = _model(
        [
            _turn(
                "write_file",
                {"path": "calc/__init__.py", "content": FIXED_CALC},
                "write-source",
            ),
            _turn("run_command", {"command": "pytest -q"}, "run-suite"),
            _finish("finish", ["calc/__init__.py"]),
        ],
    )
    instance = _instance("fixture__calc-gate-looser")
    instance.pass_to_pass = ["tests/test_missing.py::test_never_collected"]

    record = await runner.run_instance(
        _executor_factory(tmp_path, repo, created),
        model,
        instance,
        tmp_path / "pilot",
        _budgets(),
    )

    assert record.status == "ran"
    assert record.final.gate_status == "PASS"
    assert record.final.official_resolved is False
    assert record.final.verified_fix is False
    assert record.attempts[0].agreement == "gate_looser"


async def test_official_grading_failure_marks_instance_as_infrastructure_error(
    tmp_path: Path,
):
    runner = _runner_module()
    repo = make_repo(tmp_path / "source")
    created: list[_ImageLocalExecutor] = []
    model = _model(
        [
            _turn(
                "write_file",
                {"path": "calc/__init__.py", "content": FIXED_CALC},
                "write-source",
            ),
            _turn("run_command", {"command": "pytest -q"}, "run-suite"),
            _finish("finish", ["calc/__init__.py"]),
        ],
    )

    record = await runner.run_instance(
        _executor_factory(
            tmp_path,
            repo,
            created,
            fail_official_apply=True,
        ),
        model,
        _instance("fixture__calc-official-infra"),
        tmp_path / "pilot",
        _budgets(),
    )

    assert record.status == "infra_error"
    assert "official grading failed" in record.reason
    assert "patch apply failed" in record.reason
    assert record.attempts[0].official.infra_error is not None
    assert record.attempts[0].official_resolved is None
    assert record.attempts[0].agreement is None
    assert created[0].closed is True


async def test_target_that_already_passes_is_excluded(tmp_path: Path):
    runner = _runner_module()
    repo = make_repo(tmp_path / "source")
    created: list[_ImageLocalExecutor] = []

    record = await runner.run_instance(
        _executor_factory(tmp_path, repo, created),
        FakeModel(),
        _instance("fixture__calc-already-green", target=PROTECTED),
        tmp_path / "pilot",
        _budgets(),
    )

    assert record.status == "excluded"
    assert "target tests did not fail in every baseline run" in record.reason
    assert record.attempts == []
    assert record.final is None
    assert created[0].closed is True


async def test_test_patch_with_unparseable_path_is_excluded_not_infra(tmp_path: Path):
    runner = _runner_module()
    repo = make_repo(tmp_path / "source")
    created: list[_ImageLocalExecutor] = []
    instance = _instance("fixture__calc-renamed-spec").model_copy(
        update={
            "test_patch": (
                "diff --git a/tests/test_old.py b/tests/test_new.py\n"
                "similarity index 100%\n"
                "rename from tests/test_old.py\n"
                "rename to tests/test_new.py\n"
            ),
        },
    )

    record = await runner.run_instance(
        _executor_factory(tmp_path, repo, created),
        FakeModel(),
        instance,
        tmp_path / "pilot",
        _budgets(),
    )

    assert record.status == "excluded"
    assert "test patch contains an unparseable path" in record.reason
    assert record.attempts == []
    assert created[0].closed is True


async def test_baseline_at_five_minutes_is_excluded_before_agent_work(tmp_path: Path):
    runner = _runner_module()

    class SlowBaselineExecutor:
        def __init__(self) -> None:
            self.sink = MemorySink()
            self.closed = False
            self.baseline_calls = 0

        async def prepare(self, source) -> Branch:
            return Branch(id="base", run_id="slow", head="image-0", origin="image-0")

        async def run_pytest(self, branch, args, timeout_s, kind="command") -> Receipt:
            self.baseline_calls += 1
            return Receipt(
                receipt_id=f"base-{self.baseline_calls}",
                seq=self.baseline_calls,
                branch_id="base",
                kind=kind,
                cmd="pytest tests",
                exit_code=1,
                stdout_sha256=hashlib.sha256(b"").hexdigest(),
                started_at=datetime.now(timezone.utc),
                duration_s=300,
                image_before=branch.head,
                image_after=branch.head,
                junit=JunitSummary(
                    passed=[PROTECTED],
                    failed=[TARGET],
                    errors=[],
                    skipped=[],
                ),
            )

        async def close(self) -> None:
            self.closed = True

    executor = SlowBaselineExecutor()
    budgets = _budgets().model_copy(update={"baseline_limit_s": 600})

    record = await runner.run_instance(
        lambda run_id: executor,
        FakeModel(),
        _instance("fixture__calc-slow-baseline"),
        tmp_path / "pilot",
        budgets,
    )

    assert record.status == "excluded"
    assert "baseline suite took 300s" in record.reason
    assert executor.baseline_calls == 1
    assert executor.closed is True


async def test_run_pilot_skips_finished_records_without_calling_model(tmp_path: Path):
    runner = _runner_module()
    pilot_dir = tmp_path / "pilot"
    candidates = [
        _instance("fixture__calc-one"),
        _instance("fixture__calc-two"),
    ]
    for instance in candidates:
        record_dir = pilot_dir / instance.instance_id
        record_dir.mkdir(parents=True)
        record = runner.InstanceRecord(
            instance_id=instance.instance_id,
            status="ran",
            reason=None,
            run_dir=str(record_dir / "run"),
            attempts=[],
            final=None,
            cost=runner.PilotCost(
                tokens=0,
                model_dollars=None,
                sandbox_lifetime_seconds=0,
                sandbox_dollars_estimate=0,
            ),
            wall_time_s=0,
        )
        (record_dir / "record.json").write_text(
            record.model_dump_json(),
            encoding="utf-8",
        )
    model = FakeModel()

    records = await runner.run_pilot(
        lambda run_id: pytest.fail(f"executor created for skipped run {run_id}"),
        model,
        candidates,
        pilot_dir,
        n=2,
        concurrency=1,
        budgets=_budgets(),
    )

    assert [record.instance_id for record in records] == [
        "fixture__calc-one",
        "fixture__calc-two",
    ]
    assert model.requests == []
    progress = (pilot_dir / "progress.log").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["instance_id"] for line in progress] == [
        "fixture__calc-one",
        "fixture__calc-two",
    ]


async def test_run_pilot_retries_infrastructure_error_then_keeps_archive(
    tmp_path: Path,
    monkeypatch,
):
    runner = _runner_module()
    pilot_dir = tmp_path / "pilot"
    instance = _instance("fixture__calc-retry")
    started: list[str] = []
    previous = _pilot_record(
        runner,
        instance.instance_id,
        "infra_error",
        pilot_dir / instance.instance_id / "runs" / "run-1",
        "RuntimeError: temporary outage",
    )
    _persist_record(pilot_dir, previous)

    async def fake_run_instance(
        make_executor,
        model,
        current_instance,
        current_pilot_dir,
        budgets,
    ):
        del make_executor, model, budgets
        started.append(current_instance.instance_id)
        record = _pilot_record(
            runner,
            current_instance.instance_id,
            "ran",
            current_pilot_dir
            / current_instance.instance_id
            / "runs"
            / "run-2",
        )
        _persist_record(current_pilot_dir, record)
        return record

    monkeypatch.setattr(runner, "run_instance", fake_run_instance)

    records = await runner.run_pilot(
        lambda run_id: pytest.fail(f"unexpected executor construction: {run_id}"),
        FakeModel(),
        [instance],
        pilot_dir,
        n=1,
        budgets=_budgets(),
    )

    assert started == [instance.instance_id]
    assert [record.status for record in records] == ["ran"]
    final = records[0]
    assert [failure.reason for failure in final.prior_infrastructure_errors] == [
        "RuntimeError: temporary outage",
    ]
    archive_path = pilot_dir / instance.instance_id / "record.infra-1.json"
    archived = runner.InstanceRecord.model_validate_json(
        archive_path.read_text(encoding="utf-8"),
    )
    assert archived.status == "infra_error"
    assert Path(archived.run_dir).is_dir()
    persisted = runner.InstanceRecord.model_validate_json(
        (pilot_dir / instance.instance_id / "record.json").read_text(
            encoding="utf-8",
        ),
    )
    assert persisted == final


async def test_infrastructure_gate_error_is_recorded_and_retried(
    tmp_path: Path,
    monkeypatch,
):
    runner = _runner_module()
    pilot_dir = tmp_path / "pilot"
    instance = _instance("fixture__calc-gate-infra")
    run_dir = pilot_dir / instance.instance_id / "runs" / "run-1"
    filtered_path = run_dir / "attempts" / "1" / "filtered.diff"
    filtered_path.parent.mkdir(parents=True)
    filtered_path.write_text("", encoding="utf-8")
    error = (
        "infrastructure: the suite failed to load (pytest exit 4) and a "
        "second clean witness did not reproduce it"
    )
    verdict = Verdict(
        branch_id="agent1",
        status="ERROR",
        predicates=[],
        claim_audit="no_claim",
        claim_evidence="branch ended without a finish call",
        error=error,
        error_kind="infrastructure",
    )
    attempt = SimpleNamespace(
        number=1,
        worker=SimpleNamespace(
            end="finished",
            claims=None,
            receipt_ids=[],
        ),
        verdict=verdict,
        filtered_patch_path="attempts/1/filtered.diff",
        filtered_sha256=hashlib.sha256(b"").hexdigest(),
        witness_apply_sha256=hashlib.sha256(b"").hexdigest(),
    )
    result = SimpleNamespace(
        attempts=[attempt],
        final_verdict=verdict,
        verified_fix=False,
        cost={},
    )
    official = runner.OfficialRecord(
        attempt=1,
        branch_id="official1",
        apply_exit_code=0,
        test_exit_code=4,
        timed_out=False,
        log_path="official/attempt-1.log",
        log_sha256=hashlib.sha256(b"").hexdigest(),
        judgement=OfficialJudgement(
            resolved=False,
            from_fail_to_pass=[],
            failed_from_fail_to_pass=[TARGET],
            failed_from_pass_to_pass=[],
        ),
    )

    first = runner._ran_record(
        instance,
        run_dir,
        result,
        [official],
        wall_time_s=1.0,
        sandbox_usage=[],
    )

    assert first.status == "infra_error"
    assert first.reason == error
    _persist_record(pilot_dir, first)
    calls = 0

    async def fake_run_instance(
        make_executor,
        model,
        current_instance,
        current_pilot_dir,
        budgets,
    ):
        nonlocal calls
        del make_executor, model, budgets
        calls += 1
        recovered = _pilot_record(
            runner,
            current_instance.instance_id,
            "ran",
            current_pilot_dir
            / current_instance.instance_id
            / "runs"
            / "run-2",
        )
        _persist_record(current_pilot_dir, recovered)
        return recovered

    monkeypatch.setattr(runner, "run_instance", fake_run_instance)

    records = await runner.run_pilot(
        lambda run_id: pytest.fail(f"unexpected executor construction: {run_id}"),
        FakeModel(),
        [instance],
        pilot_dir,
        n=1,
        budgets=_budgets(),
    )

    assert calls == 1
    assert records[0].status == "ran"
    assert [
        prior.reason for prior in records[0].prior_infrastructure_errors
    ] == [error]
    archived = runner.InstanceRecord.model_validate_json(
        (
            pilot_dir
            / instance.instance_id
            / "record.infra-1.json"
        ).read_text(encoding="utf-8"),
    )
    assert archived.status == "infra_error"
    assert archived.reason == error


async def test_run_pilot_recovers_archived_history_without_rerunning_terminal_record(
    tmp_path: Path,
):
    runner = _runner_module()
    pilot_dir = tmp_path / "pilot"
    instance = _instance("fixture__calc-recovered")
    instance_dir = pilot_dir / instance.instance_id
    archived = _pilot_record(
        runner,
        instance.instance_id,
        "infra_error",
        instance_dir / "runs" / "run-1",
        "RuntimeError: temporary outage",
    )
    Path(archived.run_dir).mkdir(parents=True)
    (instance_dir / "record.infra-1.json").write_text(
        archived.model_dump_json(),
        encoding="utf-8",
    )
    terminal = _pilot_record(
        runner,
        instance.instance_id,
        "ran",
        instance_dir / "runs" / "run-2",
    )
    _persist_record(pilot_dir, terminal)
    model = FakeModel()

    records = await runner.run_pilot(
        lambda run_id: pytest.fail(f"executor created for terminal record {run_id}"),
        model,
        [instance],
        pilot_dir,
        n=1,
        budgets=_budgets(),
    )

    assert model.requests == []
    assert [failure.reason for failure in records[0].prior_infrastructure_errors] == [
        "RuntimeError: temporary outage",
    ]


async def test_run_pilot_stops_after_three_infrastructure_errors_then_moves_on(
    tmp_path: Path,
    monkeypatch,
):
    runner = _runner_module()
    pilot_dir = tmp_path / "pilot"
    failing = _instance("fixture__calc-always-infra")
    succeeding = _instance("fixture__calc-next")
    calls: list[str] = []
    per_instance_runs: dict[str, int] = {}

    async def fake_run_instance(
        make_executor,
        model,
        instance,
        current_pilot_dir,
        budgets,
    ):
        del make_executor, model, budgets
        calls.append(instance.instance_id)
        run_number = per_instance_runs.get(instance.instance_id, 0) + 1
        per_instance_runs[instance.instance_id] = run_number
        status = "infra_error" if instance is failing else "ran"
        record = _pilot_record(
            runner,
            instance.instance_id,
            status,
            current_pilot_dir
            / instance.instance_id
            / "runs"
            / f"run-{run_number}",
            f"RuntimeError: outage {run_number}" if status == "infra_error" else None,
        )
        _persist_record(current_pilot_dir, record)
        return record

    monkeypatch.setattr(runner, "run_instance", fake_run_instance)

    records = await runner.run_pilot(
        lambda run_id: pytest.fail(f"unexpected executor construction: {run_id}"),
        FakeModel(),
        [failing, succeeding],
        pilot_dir,
        n=1,
        budgets=_budgets(),
    )

    assert calls == [
        failing.instance_id,
        failing.instance_id,
        failing.instance_id,
        succeeding.instance_id,
    ]
    assert [record.status for record in records] == ["infra_error", "ran"]
    failed = records[0]
    assert [failure.reason for failure in failed.prior_infrastructure_errors] == [
        "RuntimeError: outage 1",
        "RuntimeError: outage 2",
    ]
    assert failed.reason == "RuntimeError: outage 3"
    instance_dir = pilot_dir / failing.instance_id
    assert (instance_dir / "record.infra-1.json").is_file()
    assert (instance_dir / "record.infra-2.json").is_file()


async def test_run_pilot_never_reruns_existing_excluded_record(tmp_path: Path):
    runner = _runner_module()
    pilot_dir = tmp_path / "pilot"
    excluded = _pilot_record(
        runner,
        "fixture__calc-excluded",
        "excluded",
        pilot_dir / "fixture__calc-excluded" / "runs" / "run-1",
        "target already passes",
    )
    ran = _pilot_record(
        runner,
        "fixture__calc-ran",
        "ran",
        pilot_dir / "fixture__calc-ran" / "runs" / "run-1",
    )
    _persist_record(pilot_dir, excluded)
    _persist_record(pilot_dir, ran)
    model = FakeModel()

    records = await runner.run_pilot(
        lambda run_id: pytest.fail(f"executor created for terminal record {run_id}"),
        model,
        [_instance(excluded.instance_id), _instance(ran.instance_id)],
        pilot_dir,
        n=1,
        budgets=_budgets(),
    )

    assert [record.status for record in records] == ["excluded", "ran"]
    assert model.requests == []


async def test_prepare_failure_is_infra_error_and_executor_is_closed(tmp_path: Path):
    runner = _runner_module()

    class FailingExecutor:
        def __init__(self) -> None:
            self.closed = False

        async def prepare(self, source) -> None:
            raise RuntimeError("sandbox failed to start")

        async def close(self) -> None:
            self.closed = True

    executor = FailingExecutor()

    record = await runner.run_instance(
        lambda run_id: executor,
        FakeModel(),
        _instance("fixture__calc-infra"),
        tmp_path / "pilot",
        _budgets(),
    )

    assert record.status == "infra_error"
    assert record.reason == "RuntimeError: sandbox failed to start"
    assert executor.closed is True
    error_path = tmp_path / "pilot" / record.instance_id / "error.txt"
    assert "RuntimeError: sandbox failed to start" in error_path.read_text(
        encoding="utf-8",
    )


async def test_run_instance_sets_cleanup_manifest_only_on_supporting_executor(
    tmp_path: Path,
):
    runner = _runner_module()

    class FailingExecutor:
        def __init__(self, *, supports_manifest: bool) -> None:
            self.closed = False
            if supports_manifest:
                self.cleanup_manifest = None

        async def prepare(self, source) -> None:
            raise RuntimeError("stop after executor setup")

        async def close(self) -> None:
            self.closed = True

    daytona_like = FailingExecutor(supports_manifest=True)
    local_like = FailingExecutor(supports_manifest=False)
    daytona_record = await runner.run_instance(
        lambda run_id: daytona_like,
        FakeModel(),
        _instance("fixture__daytona-manifest"),
        tmp_path / "pilot",
        _budgets(),
    )
    await runner.run_instance(
        lambda run_id: local_like,
        FakeModel(),
        _instance("fixture__local-no-manifest"),
        tmp_path / "pilot",
        _budgets(),
    )

    assert daytona_like.cleanup_manifest == Path(daytona_record.run_dir) / "cleanup.json"
    assert not hasattr(local_like, "cleanup_manifest")


async def test_cleanup_failure_is_recorded_without_changing_agent_outcome(
    tmp_path: Path,
):
    runner = _runner_module()
    repo = make_repo(tmp_path / "source")

    class CleanupFailingExecutor(_ImageLocalExecutor):
        async def close(self) -> None:
            await super().close()
            raise RuntimeError("snapshot delete denied")

    executor = CleanupFailingExecutor(
        tmp_path / "executors" / "run",
        repo,
        "run",
    )
    model = _model(
        [
            _turn(
                "write_file",
                {"path": "calc/__init__.py", "content": FIXED_CALC},
                "write-source",
            ),
            _turn("run_command", {"command": "pytest -q"}, "run-suite"),
            _finish("finish", ["calc/__init__.py"]),
        ],
    )

    record = await runner.run_instance(
        lambda run_id: executor,
        model,
        _instance("fixture__cleanup-failure"),
        tmp_path / "pilot",
        _budgets(),
    )

    assert record.status == "ran"
    assert len(record.attempts) == 1
    assert record.final is not None and record.final.verified_fix is True
    assert record.cleanup_error == "RuntimeError: snapshot delete denied"


async def test_run_instance_writes_repository_relative_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    runner = _runner_module()
    monkeypatch.setattr(runner, "_REPOSITORY_ROOT", tmp_path)

    class FailingExecutor:
        async def prepare(self, source) -> None:
            raise RuntimeError("sandbox failed to start")

        async def close(self) -> None:
            return None

    record = await runner.run_instance(
        lambda run_id: FailingExecutor(),
        FakeModel(),
        _instance("fixture__relative-run"),
        tmp_path / "pilot",
        _budgets(),
    )

    assert record.run_dir.startswith("pilot/fixture__relative-run/runs/")
    assert not Path(record.run_dir).is_absolute()


async def test_run_pilot_relativizes_archived_and_prior_infrastructure_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    runner = _runner_module()
    monkeypatch.setattr(runner, "_REPOSITORY_ROOT", tmp_path)
    pilot_dir = tmp_path / "pilot"
    instance = _instance("fixture__relative-retry")
    first_run = pilot_dir / instance.instance_id / "runs" / "run-1"
    previous = _pilot_record(
        runner,
        instance.instance_id,
        "infra_error",
        first_run,
        "RuntimeError: temporary outage",
    )
    _persist_record(pilot_dir, previous)

    async def fake_run_instance(
        make_executor,
        model,
        current_instance,
        current_pilot_dir,
        budgets,
    ):
        del make_executor, model, budgets
        return _pilot_record(
            runner,
            current_instance.instance_id,
            "ran",
            current_pilot_dir / current_instance.instance_id / "runs" / "run-2",
        )

    monkeypatch.setattr(runner, "run_instance", fake_run_instance)

    records = await runner.run_pilot(
        lambda run_id: pytest.fail(f"unexpected executor construction: {run_id}"),
        FakeModel(),
        [instance],
        pilot_dir,
        n=1,
        budgets=_budgets(),
    )

    archived = runner.InstanceRecord.model_validate_json(
        (pilot_dir / instance.instance_id / "record.infra-1.json").read_text(
            encoding="utf-8",
        ),
    )
    assert archived.run_dir == "pilot/fixture__relative-retry/runs/run-1"
    assert records[0].run_dir == "pilot/fixture__relative-retry/runs/run-2"
    assert records[0].prior_infrastructure_errors[0].run_dir == archived.run_dir


async def test_old_absolute_record_loads_and_resumes_without_rerunning(
    tmp_path: Path,
):
    runner = _runner_module()
    pilot_dir = tmp_path / "pilot"
    instance = _instance("fixture__old-absolute")
    absolute_run_dir = tmp_path / "old-checkout" / "pilot" / "run-1"
    record = _pilot_record(
        runner,
        instance.instance_id,
        "ran",
        absolute_run_dir,
    )
    _persist_record(pilot_dir, record)

    records = await runner.run_pilot(
        lambda run_id: pytest.fail(f"executor created for old record {run_id}"),
        FakeModel(),
        [instance],
        pilot_dir,
        n=1,
        budgets=_budgets(),
    )

    assert records[0].run_dir == str(absolute_run_dir)


def test_relative_record_path_stays_repository_relative_from_another_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    runner = _runner_module()
    repository = tmp_path / "repository"
    elsewhere = tmp_path / "elsewhere"
    repository.mkdir()
    elsewhere.mkdir()
    monkeypatch.setattr(runner, "_REPOSITORY_ROOT", repository)
    monkeypatch.chdir(elsewhere)
    record = _pilot_record(
        runner,
        "fixture__portable",
        "ran",
        Path("pilot/fixture__portable/runs/run-1"),
    )

    normalized = runner._normalize_record_paths(record)

    assert normalized.run_dir == "pilot/fixture__portable/runs/run-1"


async def test_run_pilot_bounds_concurrency_and_stops_at_requested_ran_count(
    tmp_path: Path,
    monkeypatch,
):
    runner = _runner_module()
    candidates = [_instance(f"fixture__calc-{number}") for number in range(4)]
    active = 0
    maximum_active = 0
    started: list[str] = []

    async def fake_run_instance(
        make_executor,
        model,
        instance,
        pilot_dir,
        budgets,
    ):
        nonlocal active, maximum_active
        del make_executor, model, pilot_dir, budgets
        started.append(instance.instance_id)
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1
        status = "excluded" if instance.instance_id.endswith("-0") else "ran"
        return runner.InstanceRecord(
            instance_id=instance.instance_id,
            status=status,
            reason="baseline excluded" if status == "excluded" else None,
            run_dir=str(tmp_path / "runs" / instance.instance_id),
            attempts=[],
            final=None,
            cost=runner.PilotCost(
                tokens=0,
                model_dollars=None,
                sandbox_lifetime_seconds=0,
                sandbox_dollars_estimate=0,
            ),
            wall_time_s=0,
        )

    monkeypatch.setattr(runner, "run_instance", fake_run_instance)

    records = await runner.run_pilot(
        lambda run_id: pytest.fail(f"unexpected executor construction: {run_id}"),
        FakeModel(),
        candidates,
        tmp_path / "pilot",
        n=2,
        concurrency=2,
        budgets=_budgets(),
    )

    assert started == [
        "fixture__calc-0",
        "fixture__calc-1",
        "fixture__calc-2",
    ]
    assert maximum_active == 2
    assert [record.status for record in records] == ["excluded", "ran", "ran"]
    progress = (tmp_path / "pilot" / "progress.log").read_text(
        encoding="utf-8",
    ).splitlines()
    assert [json.loads(line)["instance_id"] for line in progress] == started


def test_pilot_run_cli_loads_candidates_in_file_order(tmp_path: Path, monkeypatch):
    import receipts.cli as cli

    instances = [
        _instance("fixture__calc-first"),
        _instance("fixture__calc-second"),
    ]
    rows_path = tmp_path / "rows.jsonl"
    rows_path.write_text(
        "\n".join(instance.model_dump_json() for instance in reversed(instances)) + "\n",
        encoding="utf-8",
    )
    candidates_path = tmp_path / "candidates.txt"
    candidates_path.write_text(
        "# dataset revision test-revision\n"
        "# rules 1-3 of PREREGISTRATION.md\n"
        "fixture__calc-first\n"
        "fixture__calc-second\n",
        encoding="utf-8",
    )
    captured = {}

    async def fake_run_pilot(
        make_executor,
        model,
        candidates,
        pilot_dir,
        n,
        concurrency,
        budgets,
    ):
        captured.update(
            make_executor=make_executor,
            model=model,
            candidates=candidates,
            pilot_dir=pilot_dir,
            n=n,
            concurrency=concurrency,
            budgets=budgets,
        )
        return []

    monkeypatch.setenv("DAYTONA_API_KEY", "test-daytona-key")
    monkeypatch.setattr(cli, "run_pilot", fake_run_pilot)
    model = FakeModel()

    status = cli.main(
        [
            "pilot",
            "run",
            "--candidates",
            str(candidates_path),
            "--rows",
            str(rows_path),
            "--n",
            "2",
            "--executor",
            "daytona",
            "--out",
            str(tmp_path / "pilot"),
            "--concurrency",
            "2",
        ],
        model=model,
    )

    assert status == 0
    assert captured["model"] is model
    assert [instance.instance_id for instance in captured["candidates"]] == [
        "fixture__calc-first",
        "fixture__calc-second",
    ]
    assert captured["pilot_dir"] == tmp_path / "pilot"
    assert captured["n"] == 2
    assert captured["concurrency"] == 2
    assert captured["budgets"].baseline_limit_s == 600
    assert captured["budgets"].worker.max_turns == 60
    assert captured["budgets"].worker.max_wall_seconds == 1_500
    assert captured["budgets"].worker.max_completion_tokens == 96_000
    assert captured["budgets"].worker.prompt_token_budget == 160_000
