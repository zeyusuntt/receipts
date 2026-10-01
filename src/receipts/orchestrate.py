"""Run the planner, worker, witness verification and deterministic gate."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import shlex
import time
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

from receipts.agent.planner import Plan, make_plan
from receipts.agent.worker import Worker, WorkerBudget, WorkerOutcome
from receipts.cost import CostMeter, TokenUsage
from receipts.llm import ModelClient
from receipts.models import Baseline, Branch, Receipt, Verdict
from receipts.rundir import RunDirectory
from receipts.sandbox.protocol import Executor, ImageSource, Source
from receipts.verify.gate import evaluate
from receipts.verify.run import Attempt, establish_baseline, verify_attempt


_PYTEST_CONFIG_NAMES = {
    ".pytest.toml",
    "conftest.py",
    "pyproject.toml",
    "pytest.ini",
    "pytest.toml",
    "setup.cfg",
    "tox.ini",
}
_DISCLOSURE_TIMEOUT_S = 120
_RECEIPTS_VERSION_FALLBACK = "0.0.1"
_FREEZE_SCRIPT = """\
import importlib.metadata

packages = {
    f"{name}=={distribution.version}"
    for distribution in importlib.metadata.distributions()
    if (name := distribution.metadata.get("Name"))
}
print("\\n".join(sorted(packages, key=str.casefold)))
"""


class RunBudgets(BaseModel):
    baseline_limit_s: int = Field(default=600, gt=0)
    verification_timeout_s: int = Field(default=600, gt=0)
    worker: WorkerBudget = Field(
        default_factory=lambda: WorkerBudget(max_completion_tokens=8_000),
    )


class RunInput(BaseModel):
    source: dict[str, Any]
    issue: str
    spec_tests: list[str]
    suite_scope: str
    appeals: int
    budgets: RunBudgets


class Disclosure(BaseModel):
    model: dict[str, Any]
    receipts_version: str
    executor_kind: str
    test_digests: dict[str, str]
    pytest_config_digests: dict[str, str]
    lock_sha256: str


class AttemptResult(BaseModel):
    number: int
    worker: WorkerOutcome
    verdict: Verdict
    patch_path: str
    filtered_patch_path: str
    witness_branch_id: str
    dropped_paths: list[str]


class RunResult(BaseModel):
    input: RunInput
    baseline: Baseline
    plan: Plan
    attempts: list[AttemptResult]
    final_verdict: Verdict
    verdict_history: list[Verdict]
    selected_patch_path: str | None
    verified_fix: bool
    cost: dict[str, Any]
    wall_time_s: float
    disclosure: Disclosure
    snapshot_receipt_id: str
    checkpoint_id: str
    agent_branch_id: str


class _ReceiptCollector:
    def __init__(self) -> None:
        self.receipts: list[Receipt] = []
        self._ids: set[str] = set()

    def add(self, receipt: Receipt) -> None:
        if receipt.receipt_id in self._ids:
            return
        self._ids.add(receipt.receipt_id)
        self.receipts.append(receipt)

    def write(self, receipt: Receipt) -> None:
        self.add(receipt)

    def for_branch(self, branch_id: str) -> list[Receipt]:
        return [receipt for receipt in self.receipts if receipt.branch_id == branch_id]


class _TeeSink:
    def __init__(self, original: Any, collector: _ReceiptCollector) -> None:
        self.original = original
        self.collector = collector

    def write(self, receipt: Receipt) -> None:
        self.original.write(receipt)
        self.collector.add(receipt)


class _RecordingExecutor:
    _RECEIPT_METHODS = {
        "apply_patch",
        "patch",
        "run",
        "run_pytest",
        "snapshot",
        "write_file",
    }

    def __init__(self, inner: Executor, collector: _ReceiptCollector) -> None:
        self.inner = inner
        self.collector = collector

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self.inner, name)
        if name not in self._RECEIPT_METHODS:
            return attribute

        async def recorded(*args: Any, **kwargs: Any) -> Any:
            result = await attribute(*args, **kwargs)
            if isinstance(result, Receipt):
                self.collector.add(result)
            return result

        return recorded


def worker_initial_message(
    plan: Plan,
    issue: str,
    spec_tests: list[str],
    suite_scope: str,
) -> str:
    return "\n\n".join(
        [
            f"<issue>\n{issue}\n</issue>",
            "<specification_tests>\n"
            + "\n".join(spec_tests)
            + "\n</specification_tests>",
            f"<suite_scope>\n{suite_scope}\n</suite_scope>",
            f"<plan>\n{plan.model_dump_json(indent=2)}\n</plan>",
        ],
    )


def _full_stdout(receipt: Receipt) -> str:
    if receipt.log_path is not None:
        try:
            return Path(receipt.log_path).read_bytes().decode(errors="replace")
        except OSError:
            pass
    return receipt.stdout_tail


def _stdout_bytes(receipt: Receipt) -> bytes:
    if receipt.log_path is not None:
        try:
            return Path(receipt.log_path).read_bytes()
        except OSError:
            pass
    return receipt.stdout_tail.encode()


def _receipts_version() -> str:
    try:
        return importlib.metadata.version("receipts")
    except importlib.metadata.PackageNotFoundError:
        return _RECEIPTS_VERSION_FALLBACK


def _executor_kind(executor: Executor) -> str:
    name = type(executor).__name__
    if name.endswith("Executor"):
        name = name[: -len("Executor")]
    return name.lower()


def _model_disclosure(model: ModelClient) -> dict[str, Any]:
    config = getattr(model, "config", None)
    if isinstance(config, BaseModel):
        values = config.model_dump(mode="json")
    elif isinstance(config, dict):
        values = dict(config)
    else:
        values = {
            "model": "fake" if type(model).__name__ == "FakeModel" else None,
            "base_url": None,
            "temperature": None,
            "top_p": None,
            "thinking": False,
            "max_tokens": None,
        }
    return {"client": type(model).__name__, **values}


def _test_locations(spec_tests: list[str]) -> tuple[list[str], list[str]]:
    files: list[str] = []
    roots: list[str] = []
    for node_id in spec_tests:
        path = PurePosixPath(node_id.split("::", 1)[0])
        rendered = path.as_posix()
        if path.is_absolute() or ".." in path.parts or rendered in {"", "."}:
            continue
        if rendered not in files:
            files.append(rendered)
        parent = path.parent.as_posix()
        if parent not in {"", "."} and parent not in roots:
            roots.append(parent)
    return files, roots


def _digest_command(spec_tests: list[str]) -> str:
    test_files, test_roots = _test_locations(spec_tests)
    payload = base64.b64encode(
        json.dumps(
            {
                "test_files": test_files,
                "test_roots": test_roots,
                "config_names": sorted(_PYTEST_CONFIG_NAMES),
            },
            separators=(",", ":"),
        ).encode(),
    ).decode()
    script = f"""\
import base64
import hashlib
import json
import os
from pathlib import Path

payload = json.loads(base64.b64decode({payload!r}))
excluded = {{'.git', '.venv', '__pycache__', 'site-packages'}}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

tests = {{}}
for item in payload['test_files']:
    path = Path(item)
    if path.is_file():
        tests[path.as_posix()] = digest(path)
for item in payload['test_roots']:
    root = Path(item)
    if not root.is_dir():
        continue
    for directory, names, filenames in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name not in excluded)
        for filename in sorted(filenames):
            path = Path(directory, filename)
            if path.is_file():
                tests[path.as_posix()] = digest(path)

configs = {{}}
for directory, names, filenames in os.walk('.', followlinks=False):
    names[:] = sorted(name for name in names if name not in excluded)
    for filename in sorted(filenames):
        if filename not in payload['config_names']:
            continue
        path = Path(directory, filename)
        rendered = path.as_posix().removeprefix('./')
        configs[rendered] = digest(path)

print(json.dumps({{'test_digests': tests, 'pytest_config_digests': configs}}, sort_keys=True))
"""
    return f"python -c {shlex.quote(script)}"


async def _collect_disclosure(
    ex: Executor,
    base: Branch,
    model: ModelClient,
    raw_executor: Executor,
    spec_tests: list[str],
    run_directory: RunDirectory,
) -> Disclosure:
    digest_receipt = await ex.run(
        base,
        _digest_command(spec_tests),
        timeout_s=_DISCLOSURE_TIMEOUT_S,
    )
    if digest_receipt.timed_out or digest_receipt.exit_code != 0:
        raise RuntimeError(
            "could not hash tests and pytest configuration "
            f"(exit {digest_receipt.exit_code}, timed_out={digest_receipt.timed_out})",
        )
    try:
        digests = json.loads(_full_stdout(digest_receipt).strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("test digest command returned invalid JSON") from exc

    lock_receipt = await ex.run(
        base,
        f"python -c {shlex.quote(_FREEZE_SCRIPT)}",
        timeout_s=_DISCLOSURE_TIMEOUT_S,
    )
    if lock_receipt.timed_out or lock_receipt.exit_code != 0:
        raise RuntimeError(
            "dependency snapshot failed "
            f"(exit {lock_receipt.exit_code}, timed_out={lock_receipt.timed_out})",
        )
    lock_bytes = _stdout_bytes(lock_receipt)
    run_directory.write_bytes("lock.txt", lock_bytes)

    return Disclosure(
        model=_model_disclosure(model),
        receipts_version=_receipts_version(),
        executor_kind=_executor_kind(raw_executor),
        test_digests=digests["test_digests"],
        pytest_config_digests=digests["pytest_config_digests"],
        lock_sha256=hashlib.sha256(lock_bytes).hexdigest(),
    )


def _patch_text(attempt: Attempt) -> str:
    if attempt.patch.diff is None or attempt.patch.diff.patch_path is None:
        return ""
    try:
        return Path(attempt.patch.diff.patch_path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _appeal_evidence(verdict: Verdict) -> str:
    failed = set(verdict.failed_predicate_ids())
    lines = [
        f"{predicate.id}: {predicate.evidence}"
        for predicate in verdict.predicates
        if predicate.id in failed
    ]
    lines.append(f"Claim audit: {verdict.claim_evidence}")
    return "\n".join(lines)


def _cost_summary(
    model: ModelClient,
    disclosure: Disclosure,
    collector: _ReceiptCollector,
    worker_log: Path,
) -> dict[str, Any]:
    existing = getattr(model, "_meter", None)
    meter = existing if isinstance(existing, CostMeter) else CostMeter()
    if not isinstance(existing, CostMeter) and worker_log.is_file():
        model_name = str(disclosure.model.get("model") or disclosure.model["client"])
        for line in worker_log.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            meter.add_usage(model_name, TokenUsage.model_validate(row["usage"]))
    meter.add_sandbox_seconds(
        sum(receipt.duration_s for receipt in collector.receipts),
    )
    return meter.summary()


async def fix(
    ex: Executor,
    model: ModelClient,
    source: Source,
    issue: str,
    spec_tests: list[str],
    suite_scope: str,
    run_dir: Path,
    appeals: int = 1,
    budgets: RunBudgets | None = None,
) -> RunResult:
    if appeals < 0:
        raise ValueError("appeals cannot be negative")
    started = time.monotonic()
    budget = budgets or RunBudgets()
    run_directory = RunDirectory(run_dir)
    run_input = RunInput(
        source=source.model_dump(mode="json"),
        issue=issue,
        spec_tests=spec_tests,
        suite_scope=suite_scope,
        appeals=appeals,
        budgets=budget,
    )
    run_directory.write_json("input.json", run_input)

    collector = _ReceiptCollector()
    original_sink = getattr(ex, "sink", None)
    sink_replaced = False
    if original_sink is not None:
        try:
            sink_run_dir = getattr(original_sink, "run_dir", None)
            same_run_directory = (
                sink_run_dir is not None
                and Path(sink_run_dir).resolve() == run_dir.resolve()
            )
            replacement = (
                collector
                if same_run_directory
                else _TeeSink(original_sink, collector)
            )
            setattr(ex, "sink", replacement)
            sink_replaced = True
        except (AttributeError, TypeError):
            pass
    recording = _RecordingExecutor(ex, collector)

    try:
        base = await recording.prepare(source)
        baseline = await establish_baseline(
            recording,
            base,
            suite_scope,
            spec_tests,
            budget.baseline_limit_s,
        )
        run_directory.write_json("baseline.json", baseline)

        disclosure = await _collect_disclosure(
            recording,
            base,
            model,
            ex,
            spec_tests,
            run_directory,
        )
        run_directory.write_json("disclosure.json", disclosure)

        snapshot = await recording.snapshot(base)
        if snapshot.timed_out or snapshot.exit_code != 0 or snapshot.snapshot_sha is None:
            raise RuntimeError(
                "snapshot failed "
                f"(exit {snapshot.exit_code}, timed_out={snapshot.timed_out})",
            )
        checkpoint = await recording.checkpoint(base)
        await recording.release(base)
        (agent,) = await recording.fork(checkpoint, 1, prefix="agent")

        plan, _ = await make_plan(
            model,
            recording,
            agent,
            issue,
            baseline,
            spec_tests,
        )
        run_directory.write_json("plan.json", plan)

        attempt_results: list[AttemptResult] = []
        verdict_history: list[Verdict] = []
        selected_patch_path: str | None = None
        worker_log = run_directory.path("agent/worker.jsonl")
        with worker_log.open("a", encoding="utf-8") as writer:
            worker = Worker(
                model=model,
                executor=recording,
                branch=agent,
                initial_message=worker_initial_message(
                    plan,
                    issue,
                    spec_tests,
                    suite_scope,
                ),
                writer=writer,
                repo_root=source.workdir if isinstance(source, ImageSource) else None,
            )
            outcome = await worker.attempt(budget.worker)

            for attempt_number in range(1, appeals + 2):
                verified = await verify_attempt(
                    recording,
                    agent,
                    checkpoint,
                    snapshot.snapshot_sha,
                    suite_scope,
                    budget.verification_timeout_s,
                    attempt_number,
                )
                agent_receipts = [
                    receipt
                    for receipt in collector.for_branch(agent.id)
                    if receipt.receipt_id != verified.patch.receipt_id
                ]
                verdict = evaluate(
                    branch_id=agent.id,
                    witness_id=verified.witness.id,
                    baseline=baseline,
                    origin=checkpoint.id,
                    receipts=agent_receipts,
                    patch=verified.patch,
                    apply=verified.apply,
                    verification=verified.verification,
                    filtered_sha256=verified.filtered_sha256,
                    claims=outcome.claims,
                )
                verdict_history.append(verdict)

                attempt_root = f"attempts/{attempt_number}"
                patch_path = f"{attempt_root}/patch.diff"
                filtered_path = f"{attempt_root}/filtered.diff"
                run_directory.write_text(patch_path, _patch_text(verified))
                run_directory.write_text(filtered_path, verified.filtered_patch)
                run_directory.write_receipts(
                    f"{attempt_root}/witness/receipts.jsonl",
                    collector.for_branch(verified.witness.id),
                )
                run_directory.write_json(f"{attempt_root}/verdict.json", verdict)
                attempt_results.append(
                    AttemptResult(
                        number=attempt_number,
                        worker=outcome,
                        verdict=verdict,
                        patch_path=patch_path,
                        filtered_patch_path=filtered_path,
                        witness_branch_id=verified.witness.id,
                        dropped_paths=verified.dropped,
                    ),
                )
                run_directory.write_receipts(
                    "agent/receipts.jsonl",
                    collector.for_branch(agent.id),
                )
                if verified.witness_provisioned:
                    await recording.release(verified.witness)

                if verdict.status == "PASS":
                    selected_patch_path = filtered_path
                    break
                if verdict.status != "REJECTED" or attempt_number > appeals:
                    break
                outcome = await worker.appeal(
                    _appeal_evidence(verdict),
                    budget.worker,
                )

        final_verdict = verdict_history[-1]
        cost = _cost_summary(model, disclosure, collector, worker_log)
        run_directory.write_json("cost.json", cost)
        result = RunResult(
            input=run_input,
            baseline=baseline,
            plan=plan,
            attempts=attempt_results,
            final_verdict=final_verdict,
            verdict_history=verdict_history,
            selected_patch_path=selected_patch_path,
            verified_fix=final_verdict.status == "PASS",
            cost=cost,
            wall_time_s=time.monotonic() - started,
            disclosure=disclosure,
            snapshot_receipt_id=snapshot.receipt_id,
            checkpoint_id=checkpoint.id,
            agent_branch_id=agent.id,
        )
        run_directory.write_json("result.json", result)
        await recording.release(agent)
        return result
    finally:
        if sink_replaced:
            setattr(ex, "sink", original_sink)


__all__ = [
    "AttemptResult",
    "Disclosure",
    "RunBudgets",
    "RunInput",
    "RunResult",
    "fix",
    "worker_initial_message",
]
