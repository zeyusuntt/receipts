"""Run the planner, worker, witness verification and deterministic gate."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import re
import shlex
import time
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field

from receipts.agent.planner import Plan, make_plan
from receipts.agent.worker import (
    Worker,
    WorkerBudget,
    WorkerOutcome,
    WorkerToolProgress,
)
from receipts.cost import (
    CostMeter,
    TokenUsage,
    estimate_model_dollars,
    token_count,
)
from receipts.llm import ModelClient
from receipts.models import (
    Baseline,
    Branch,
    Checkpoint,
    PatchScope,
    PredicateResult,
    Receipt,
    Verdict,
    bounded_target_failure_text,
)
from receipts.patchscope import default_protected_modules
from receipts.rundir import RunDirectory
from receipts.sandbox.protocol import Executor, ImageSource, Source
from receipts.verify.gate import evaluate
from receipts.verify.review import ReviewMode, ReviewResult, ReviewVotes, review_votes
from receipts.verify.run import (
    Attempt,
    confirm_load_failure,
    establish_baseline,
    verify_attempt,
)


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
_DIGEST_JSON_MARKER = "RECEIPTS_TEST_DIGESTS_JSON:"


def _short_id(identifier: str) -> str:
    """Eight characters that identify a checkpoint: a Docker "sha256:..." id loses its prefix first."""

    return identifier.split(":", 1)[-1][:8]
_RECEIPTS_VERSION_FALLBACK = "0.0.1"
_FREEZE_SCRIPT = """\
# Runs inside the task sandbox, so it must work on Python 3.7.
packages = set()
try:
    import importlib.metadata as metadata
except ImportError:
    import pkg_resources

    for dist in pkg_resources.working_set:
        packages.add(dist.project_name + "==" + dist.version)
else:
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            packages.add(name + "==" + distribution.version)
print("\\n".join(sorted(packages, key=str.casefold)))
"""


class RunBudgets(BaseModel):
    baseline_limit_s: int = Field(default=600, gt=0)
    verification_timeout_s: int = Field(default=600, gt=0)
    worker: WorkerBudget = Field(
        default_factory=lambda: WorkerBudget(
            max_turns=60,
            max_wall_seconds=1_500,
            max_completion_tokens=96_000,
            prompt_token_budget=160_000,
        ),
    )


class RunInput(BaseModel):
    source: dict[str, Any]
    issue: str
    spec_tests: list[str]
    spec_paths: list[str] = Field(default_factory=list)
    suite_scope: str
    appeals: int
    budgets: RunBudgets
    review: ReviewMode = "off"


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
    filtered_sha256: str | None = None
    witness_apply_sha256: str | None = None


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
    checkpoint: Checkpoint
    checkpoint_id: str
    agent_branch_id: str
    cleanup_error: str | None = None


class ProgressEvent(BaseModel):
    kind: Literal[
        "baseline",
        "checkpoint",
        "agent_tool",
        "agent_finish",
        "witness",
        "check",
        "appeal",
        "verdict",
    ]
    message: str
    duration_s: float | None = None
    action: Literal["read", "edit", "write", "run"] | None = None
    exit_code: int | None = None
    check_id: str | None = None
    passed: bool | None = None
    attempt: int | None = None


ProgressCallback = Callable[[ProgressEvent], None]


def _emit(progress: ProgressCallback | None, event: ProgressEvent) -> None:
    if progress is not None:
        progress(event)


def _first_sentence(summary: str) -> str:
    text = " ".join(summary.strip().split())
    match = re.match(r"^.*?[.!?](?=\s|$)", text)
    return match.group(0) if match is not None else text


def _predicate_progress_message(
    predicate: Any,
    baseline: Baseline,
    changed_files: int,
) -> str:
    if not predicate.passed:
        return predicate.evidence
    if predicate.id == "R1_fail_to_pass":
        count = len(baseline.target)
        return f"{count} of {count} target tests pass"
    if predicate.id == "R2_pass_to_pass":
        count = len(baseline.protected)
        return f"{count} of {count} baseline-passing tests still pass"
    if predicate.id == "R3_no_shrink":
        return f"all {len(baseline.collected_ids)} baseline tests collected; skips unchanged"
    if predicate.id == "R4_patch_scope":
        return (
            f"{changed_files} file{'s' if changed_files != 1 else ''} changed, "
            "no tests or config"
        )
    if predicate.id == "R5_provenance":
        return "agent and witness chains are intact; applied digest matches"
    return predicate.evidence


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
    target_map: dict[str, list[str]] | None = None,
    target_failure_text: dict[str, str] | None = None,
) -> str:
    sections = [
        f"<issue>\n{issue}\n</issue>",
        "<specification_tests>\n"
        + "\n".join(spec_tests)
        + "\n</specification_tests>",
    ]
    if spec_tests:
        failures = bounded_target_failure_text(
            spec_tests,
            target_failure_text or {},
        )
        failure_lines = [
            f"Target: {target}\n{failures[target]}"
            for target in spec_tests
        ]
        sections.append(
            "<baseline_failures>\n"
            + "\n".join(failure_lines)
            + "\n</baseline_failures>",
        )
    mapped = {
        dataset_id: full_ids
        for dataset_id, full_ids in (target_map or {}).items()
        if full_ids != [dataset_id]
    }
    if mapped:
        mapping_lines = ["Mapped dataset test ids to full collected ids:"]
        for dataset_id, full_ids in mapped.items():
            mapping_lines.append(f"- {dataset_id}")
            mapping_lines.extend(f"  - {full_id}" for full_id in full_ids)
        sections.append("<target_id_mapping>\n" + "\n".join(mapping_lines) + "\n</target_id_mapping>")
    sections.extend(
        [
            f"<suite_scope>\n{suite_scope}\n</suite_scope>",
            f"<plan>\n{plan.model_dump_json(indent=2, exclude={'usage', 'finish_reason'})}\n</plan>",
        ],
    )
    return "\n\n".join(sections)


def _full_stdout(receipt: Receipt, *, required: bool = False) -> str:
    if receipt.log_path is not None:
        try:
            return Path(receipt.log_path).read_bytes().decode(errors="replace")
        except OSError as exc:
            if required:
                raise RuntimeError(
                    f"complete stdout unavailable for receipt {receipt.receipt_id}",
                ) from exc
    if required:
        raise RuntimeError(
            f"complete stdout unavailable for receipt {receipt.receipt_id}",
        )
    return receipt.stdout_tail


def _tree_entries(receipt: Receipt) -> list[str]:
    return [entry for entry in _full_stdout(receipt, required=True).split("\0") if entry]


def _protected_name(entry: str) -> str:
    return entry[:-3] if entry.endswith(".py") else entry


async def _build_patch_scope(
    ex: Executor,
    base: Branch,
    snapshot_sha: str,
) -> PatchScope:
    root_receipt = await ex.run(
        base,
        "git -c core.quotePath=false ls-tree -z --name-only "
        + shlex.quote(snapshot_sha),
        timeout_s=_DISCLOSURE_TIMEOUT_S,
    )
    if root_receipt.timed_out or root_receipt.exit_code != 0:
        raise RuntimeError(
            "could not list checkpoint root "
            f"(exit {root_receipt.exit_code}, timed_out={root_receipt.timed_out})",
        )
    root_entries = _tree_entries(root_receipt)

    src_receipt = await ex.run(
        base,
        "git -c core.quotePath=false ls-tree -z --name-only "
        + shlex.quote(f"{snapshot_sha}:src"),
        timeout_s=_DISCLOSURE_TIMEOUT_S,
    )
    if src_receipt.timed_out:
        raise RuntimeError("listing checkpoint src tree timed out")
    src_entries = _tree_entries(src_receipt) if src_receipt.exit_code == 0 else []

    c0_top_level = sorted(
        set(root_entries).union(f"src/{entry}" for entry in src_entries),
    )
    repository_names = {
        _protected_name(entry)
        for entry in [*root_entries, *src_entries]
        if not entry.startswith(".")
    }
    protected_names = sorted(set(default_protected_modules()).union(repository_names))
    return PatchScope(
        protected_names=protected_names,
        c0_top_level=c0_top_level,
    )


async def build_patch_scope(
    ex: Executor, base: Branch, snapshot_sha: str,
) -> PatchScope:
    """Expose the pilot's checkpoint-derived patch scope for receipt replay."""
    return await _build_patch_scope(ex, base, snapshot_sha)


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
        rendered = path.as_posix()
        rendered = rendered[2:] if rendered.startswith('./') else rendered
        configs[rendered] = digest(path)

# Start a fresh line even if merged startup diagnostics have no final newline.
print('\\n' + {_DIGEST_JSON_MARKER!r} + json.dumps({{'test_digests': tests, 'pytest_config_digests': configs}}, sort_keys=True))
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
        # Executors may merge stderr into the log in either order. Only the
        # producer's single marked line is machine-readable evidence.
        marked = [
            line[len(_DIGEST_JSON_MARKER):]
            for line in _full_stdout(digest_receipt).splitlines()
            if line.startswith(_DIGEST_JSON_MARKER)
        ]
        if len(marked) != 1:
            raise ValueError("expected exactly one marked test digest JSON line")
        digests = json.loads(marked[0])
    except ValueError as exc:
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


def _with_review(verdict: Verdict, result: ReviewVotes, *, advisory: bool = False) -> Verdict:
    """Add R8 to a verdict the gate passed. Only a unanimous objection rejects it; nothing can pass it.

    In advisory mode the review is recorded as R8_review_advisory and never changes the verdict.
    """
    objecting = sum(1 for vote in result.votes if vote.objections)
    if result.veto:
        evidence = f"{objecting} of {len(result.votes)} independent reviews object: " + "; ".join(
            f'"{objection.requirement}": {objection.problem} ({objection.location})'
            for objection in result.votes[0].objections
        )
    else:
        evidence = "no objection" if objecting == 0 else (
            f"no veto ({objecting} of {len(result.votes)} independent reviews object)"
        )
        dropped = sum(len(vote.dropped) for vote in result.votes)
        if dropped:
            evidence += f" ({dropped} ungrounded objection(s) dropped)"
        errors = [vote.error for vote in result.votes if vote.error]
        if errors:
            evidence += f" (review unavailable: {errors[0]})"
    if advisory:
        r8 = PredicateResult(id="R8_review_advisory", passed=not result.veto, evidence=f"advisory: {evidence}")
    else:
        r8 = PredicateResult(id="R8_review", passed=not result.veto, evidence=evidence)
    predicates = [p for p in verdict.predicates if p.id != "R6_claim_audit"]
    predicates += [r8] + [p for p in verdict.predicates if p.id == "R6_claim_audit"]
    status = "REJECTED" if result.veto and not advisory else verdict.status
    return verdict.model_copy(update={"predicates": predicates, "status": status})


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
    plan: Plan,
    reviews: Sequence[ReviewResult] = (),
    reviewer: ModelClient | None = None,
) -> dict[str, Any]:
    existing = getattr(model, "_meter", None)
    meter = existing if isinstance(existing, CostMeter) else CostMeter()
    model_name = str(disclosure.model.get("model") or disclosure.model["client"])
    planner_usage = plan.usage
    if not isinstance(existing, CostMeter) and worker_log.is_file():
        for line in worker_log.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            meter.add_usage(model_name, TokenUsage.model_validate(row["usage"]))
    if not isinstance(existing, CostMeter) and planner_usage is not None:
        meter.add_usage(model_name, planner_usage)
    # Review calls are counted from their records unless the reviewer shares the agent's meter.
    reviewer_meter = getattr(reviewer, "_meter", None)
    if reviewer_meter is not meter or not isinstance(reviewer_meter, CostMeter):
        reviewer_config = getattr(reviewer, "config", None)
        reviewer_name = str(getattr(reviewer_config, "model", None) or model_name)
        for review in reviews:
            if review.usage is not None:
                meter.add_usage(reviewer_name, review.usage)
    meter.add_sandbox_seconds(
        sum(receipt.duration_s for receipt in collector.receipts),
    )
    model_retries: dict[str, int] = {}
    planner_retries = getattr(plan, "retries", {})
    if isinstance(planner_retries, dict):
        for kind, count in planner_retries.items():
            if isinstance(kind, str) and type(count) is int and count > 0:
                model_retries[kind] = model_retries.get(kind, 0) + count
    for review in reviews:
        for kind, count in (review.retries or {}).items():
            if isinstance(kind, str) and type(count) is int and count > 0:
                model_retries[kind] = model_retries.get(kind, 0) + count
    if worker_log.is_file():
        for line in worker_log.read_text(encoding="utf-8").splitlines():
            retries = json.loads(line).get("retries", {})
            if not isinstance(retries, dict):
                continue
            for kind, count in retries.items():
                if isinstance(kind, str) and type(count) is int and count > 0:
                    model_retries[kind] = model_retries.get(kind, 0) + count

    summary = meter.summary()
    summary["planner_tokens"] = (
        token_count(planner_usage) if planner_usage is not None else 0
    )
    summary["planner_dollars"] = (
        estimate_model_dollars(model_name, planner_usage)
        if planner_usage is not None
        else 0.0
    )
    summary["model_retries"] = {
        kind: model_retries[kind]
        for kind in sorted(model_retries)
    }
    return summary


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
    spec_paths: list[str] | None = None,
    progress: ProgressCallback | None = None,
    review: ReviewMode = "off",
    reviewer: ModelClient | None = None,
) -> RunResult:
    if appeals < 0:
        raise ValueError("appeals cannot be negative")
    started = time.monotonic()
    budget = budgets or RunBudgets()
    effective_spec_paths = sorted(
        set(spec_paths or []).union(
            node_id.split("::", 1)[0] for node_id in spec_tests
        ),
    )
    run_directory = RunDirectory(run_dir)
    run_input = RunInput(
        source=source.model_dump(mode="json"),
        issue=issue,
        spec_tests=spec_tests,
        spec_paths=effective_spec_paths,
        suite_scope=suite_scope,
        appeals=appeals,
        budgets=budget,
        review=review,
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
        baseline_started = time.monotonic()
        baseline = await establish_baseline(
            recording,
            base,
            suite_scope,
            spec_tests,
            budget.baseline_limit_s,
            spec_paths=effective_spec_paths,
        )
        _emit(
            progress,
            ProgressEvent(
                kind="baseline",
                message=(
                    f"{len(baseline.target)} failing spec test{'s' if len(baseline.target) != 1 else ''}, "
                    f"{len(baseline.protected)} passing tests"
                ),
                duration_s=time.monotonic() - baseline_started,
            ),
        )

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
        scope = await _build_patch_scope(
            recording,
            base,
            snapshot.snapshot_sha,
        )
        baseline = baseline.model_copy(update={"scope": scope})
        run_directory.write_json("baseline.json", baseline)
        checkpoint = await recording.checkpoint(base)
        source_name = source.image if isinstance(source, ImageSource) else source.url
        _emit(
            progress,
            ProgressEvent(
                kind="checkpoint",
                message=f"built from {source_name} · checkpoint {_short_id(checkpoint.id)}",
                duration_s=time.monotonic() - started,
            ),
        )
        await recording.release(base)
        (agent,) = await recording.fork(checkpoint, 1, prefix="agent")
        scratch_path = recording.scratch_path(agent)

        plan, _ = await make_plan(
            model,
            recording,
            agent,
            issue,
            baseline,
            baseline.target,
        )
        plan_json = plan.model_dump(mode="json")
        planner_retries = getattr(plan, "retries", {})
        plan_json["retries"] = planner_retries if isinstance(planner_retries, dict) else {}
        run_directory.write_json("plan.json", plan_json)

        attempt_results: list[AttemptResult] = []
        verdict_history: list[Verdict] = []
        reviews: list[ReviewResult] = []
        selected_patch_path: str | None = None
        worker_log = run_directory.path("agent/worker.jsonl")
        with worker_log.open("a", encoding="utf-8") as writer:
            def report_tool(event: WorkerToolProgress) -> None:
                _emit(
                    progress,
                    ProgressEvent(
                        kind="agent_tool",
                        action=event.action,
                        message=event.value,
                        exit_code=event.exit_code,
                        duration_s=event.duration_s,
                    ),
                )

            worker = Worker(
                model=model,
                executor=recording,
                branch=agent,
                initial_message=worker_initial_message(
                    plan,
                    issue,
                    baseline.target,
                    suite_scope,
                    baseline.target_map,
                    baseline.target_failure_text,
                ),
                writer=writer,
                repo_root=source.workdir if isinstance(source, ImageSource) else None,
                scratch_path=scratch_path,
                progress=report_tool if progress is not None else None,
            )
            outcome = await worker.attempt(budget.worker)
            _emit(
                progress,
                ProgressEvent(
                    kind="agent_finish",
                    message=_first_sentence(outcome.summary),
                    attempt=1,
                ),
            )

            for attempt_number in range(1, appeals + 2):
                witness_started = time.monotonic()
                verified = await verify_attempt(
                    recording,
                    agent,
                    checkpoint,
                    snapshot.snapshot_sha,
                    suite_scope,
                    budget.verification_timeout_s,
                    attempt_number,
                    spec_paths=baseline.spec_paths,
                    scope=baseline.scope,
                )
                changed_paths = (
                    [changed.path for changed in verified.patch.diff.files]
                    if verified.patch.diff is not None
                    else []
                )
                dropped = set(verified.dropped)
                apply_succeeded = verified.apply.exit_code == 0
                applied_paths = (
                    [path for path in changed_paths if path not in dropped]
                    if apply_succeeded
                    else []
                )
                witness_origin = (
                    f"fresh sandbox from checkpoint {_short_id(checkpoint.id)}"
                    if verified.witness_provisioned
                    else f"witness not provisioned from checkpoint {_short_id(checkpoint.id)}"
                )
                apply_status = (
                    ""
                    if apply_succeeded
                    else f"; apply failed (exit {verified.apply.exit_code})"
                )
                _emit(
                    progress,
                    ProgressEvent(
                        kind="witness",
                        message=(
                            f"{verified.witness.id}; {witness_origin}; files applied "
                            f"{', '.join(applied_paths) if applied_paths else 'none'}; "
                            f"dropped {', '.join(verified.dropped) if verified.dropped else 'none'}"
                            f"{apply_status}"
                        ),
                        duration_s=time.monotonic() - witness_started,
                        attempt=attempt_number,
                    ),
                )
                load_confirmation = None
                if (
                    verified.verification is not None
                    and not verified.verification.timed_out
                    and verified.verification.exit_code in (2, 3, 4)
                ):
                    load_confirmation = await confirm_load_failure(
                        recording,
                        checkpoint,
                        verified.filtered_patch,
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
                    load_confirmation_apply=(
                        load_confirmation.apply
                        if load_confirmation is not None
                        else None
                    ),
                    load_confirmation=(
                        load_confirmation.verification
                        if load_confirmation is not None
                        else None
                    ),
                )
                review_result = None
                if review != "off" and verdict.status == "PASS":
                    review_result = await review_votes(
                        reviewer or model,
                        issue,
                        spec_tests,
                        verified.filtered_patch,
                        default_protected_modules(),
                    )
                    reviews.extend(review_result.votes)
                    verdict = _with_review(verdict, review_result, advisory=review == "advisory")
                verdict_history.append(verdict)
                changed_files = len(changed_paths)
                for predicate in verdict.predicates:
                    if predicate.id == "R6_claim_audit":
                        if verdict.claim_audit == "contradicted":
                            _emit(
                                progress,
                                ProgressEvent(
                                    kind="check",
                                    check_id="R6 advisory",
                                    message=verdict.claim_evidence,
                                    passed=False,
                                    attempt=attempt_number,
                                ),
                            )
                        continue
                    _emit(
                        progress,
                        ProgressEvent(
                            kind="check",
                            check_id=predicate.id,
                            message=_predicate_progress_message(
                                predicate,
                                baseline,
                                changed_files,
                            ),
                            passed=predicate.passed,
                            attempt=attempt_number,
                        ),
                    )

                attempt_root = f"attempts/{attempt_number}"
                patch_path = f"{attempt_root}/patch.diff"
                filtered_path = f"{attempt_root}/filtered.diff"
                run_directory.write_text(patch_path, _patch_text(verified))
                filtered_bytes = verified.filtered_patch.encode("utf-8")
                written_filtered = run_directory.write_bytes(
                    filtered_path,
                    filtered_bytes,
                )
                written_sha256 = hashlib.sha256(
                    written_filtered.read_bytes(),
                ).hexdigest()
                if written_sha256 != verified.filtered_sha256:
                    raise RuntimeError(
                        "filtered.diff does not match the verified digest after writing",
                    )
                run_directory.write_receipts(
                    f"{attempt_root}/witness/receipts.jsonl",
                    collector.for_branch(verified.witness.id),
                )
                if load_confirmation is not None:
                    run_directory.write_receipts(
                        f"{attempt_root}/confirmation/receipts.jsonl",
                        collector.for_branch(load_confirmation.branch.id),
                    )
                run_directory.write_json(f"{attempt_root}/verdict.json", verdict)
                if review_result is not None:
                    run_directory.write_json(
                        f"{attempt_root}/review.json",
                        {"veto": review_result.veto, **review_result.model_dump(mode="json")},
                    )
                attempt_results.append(
                    AttemptResult(
                        number=attempt_number,
                        worker=outcome,
                        verdict=verdict,
                        patch_path=patch_path,
                        filtered_patch_path=filtered_path,
                        witness_branch_id=verified.witness.id,
                        dropped_paths=verified.dropped,
                        filtered_sha256=verified.filtered_sha256,
                        witness_apply_sha256=(
                            verified.apply.patch_sha256
                            if verified.apply is not None
                            else None
                        ),
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
                appeal_message = _appeal_evidence(verdict)
                _emit(
                    progress,
                    ProgressEvent(
                        kind="appeal",
                        message=appeal_message.replace("\n", "; "),
                        attempt=attempt_number,
                    ),
                )
                outcome = await worker.appeal(
                    appeal_message,
                    budget.worker,
                )
                _emit(
                    progress,
                    ProgressEvent(
                        kind="agent_finish",
                        message=_first_sentence(outcome.summary),
                        attempt=attempt_number + 1,
                    ),
                )

        final_verdict = verdict_history[-1]
        _emit(
            progress,
            ProgressEvent(
                kind="verdict",
                message={
                    "PASS": "VERIFIED",
                    "REJECTED": "REJECTED",
                    "ERROR": "ERROR",
                }[final_verdict.status],
                passed=final_verdict.status == "PASS",
                attempt=len(verdict_history),
            ),
        )
        cost = _cost_summary(model, disclosure, collector, worker_log, plan, reviews, reviewer or model)
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
            checkpoint=checkpoint,
            checkpoint_id=checkpoint.id,
            agent_branch_id=agent.id,
        )
        run_directory.write_json("result.json", result)
        try:
            await recording.release(agent)
        except Exception as exc:
            result = result.model_copy(
                update={"cleanup_error": f"{type(exc).__name__}: {exc}"},
            )
            run_directory.write_json("result.json", result)
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
    "ProgressEvent",
    "fix",
    "worker_initial_message",
]
