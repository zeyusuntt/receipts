"""Portable final-attempt bundles and fresh, model-free receipt verification."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from receipts.models import Branch, ClaimAudit, PredicateId, Verdict, VerdictStatus
from receipts.orchestrate import RunBudgets, RunResult, build_patch_scope
from receipts.patchscope import default_protected_modules, filter_patch
from receipts.pilot.grade import grade_patch
from receipts.pilot.runner import (
    InstanceRecord, baseline_guard, complete_shielded, shield_cleanup_methods,
)
from receipts.sandbox.protocol import Executor
from receipts.sandbox.sink import MemorySink
from receipts.swerebench import Instance, to_task
from receipts.verify.gate import evaluate
from receipts.verify.run import confirm_load_failure, establish_baseline, verify_attempt


def _instance_id(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.-]+", value) is None or value in {".", ".."}:
        raise ValueError(f"invalid instance id: {value!r}")
    return value


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BundleRun(BaseModel):
    run_id: str
    executor_kind: str | None
    model: dict[str, Any]
    code_version: str | None = None
    budgets: RunBudgets = Field(default_factory=RunBudgets)


class ShippedPatch(BaseModel):
    number: int = Field(ge=1)
    patch: str
    sha256: str
    filtered_sha256: str
    agent_patch: str
    agent_patch_sha256: str


class BundleClaims(BaseModel):
    gate_status: VerdictStatus
    failed_predicate_ids: list[PredicateId]
    claim_audit: ClaimAudit
    official_resolved: bool | None


class Bundle(BaseModel):
    schema_version: Literal["receipts-bundle/1"] = Field(alias="schema")
    instance: Instance
    run: BundleRun
    shipped: ShippedPatch
    claims: BundleClaims


def export_bundles(pilot_dir: Path, rows_path: Path, out_dir: Path) -> list[Path]:
    """Export the final attempt of each recorded instance, checking its gate digest."""
    from receipts.cli import load_pilot_candidates

    if not pilot_dir.is_dir():
        raise ValueError(f"pilot directory does not exist: {pilot_dir}")
    records: list[InstanceRecord] = []
    for path in sorted(pilot_dir.glob("*/record.json")):
        _instance_id(path.parent.name)
        record = InstanceRecord.model_validate_json(path.read_bytes())
        _instance_id(record.instance_id)
        if record.instance_id != path.parent.name:
            raise ValueError(f"record instance id differs from directory: {path}")
        if record.attempts:
            records.append(record)
    # Use the pilot's dataset loader, including aliases, gold-patch removal,
    # duplicate detection and missing-row errors. The ID file is temporary.
    with tempfile.TemporaryDirectory(prefix="receipts-export-") as temporary:
        candidates = Path(temporary) / "candidates.txt"
        candidates.write_text("".join(r.instance_id + "\n" for r in records), encoding="utf-8")
        instances = load_pilot_candidates(candidates, rows_path)

    bundles: list[tuple[str, Bundle]] = []
    for record, instance in zip(records, instances, strict=True):
        run_dir = Path(record.run_dir)
        if run_dir.is_absolute() or not run_dir.resolve().is_relative_to(Path.cwd().resolve()):
            raise ValueError(f"run_dir must stay inside cwd: {record.run_dir}")
        result = RunResult.model_validate_json((run_dir / "result.json").read_bytes())
        if len(result.attempts) != len(record.attempts):
            raise ValueError(f"attempt count differs from record: {record.instance_id}")
        attempt = result.attempts[-1]
        final = record.attempts[-1]
        attempt_dir = run_dir / "attempts" / str(attempt.number)
        # read_bytes avoids newline normalization, including CRLF patches.
        patch = (attempt_dir / "filtered.diff").read_bytes().decode("utf-8")
        agent_patch = (attempt_dir / "patch.diff").read_bytes().decode("utf-8")
        digest = _sha(patch)
        if digest != final.filtered_sha256:
            raise ValueError(
                f"{record.instance_id}: patch digest {digest} differs from recorded "
                f"filtered_sha256 {final.filtered_sha256}",
            )
        verdict = Verdict.model_validate_json((attempt_dir / "verdict.json").read_bytes())
        if (verdict.status != final.gate_status
                or verdict.failed_predicate_ids() != final.failed_predicate_ids
                or verdict.claim_audit != final.claim_audit
                or result.final_verdict != verdict
                or (record.final is not None and record.final.gate_status != verdict.status)):
            raise ValueError(f"final verdict differs from record: {record.instance_id}")
        disclosure = json.loads((run_dir / "disclosure.json").read_bytes())
        bundles.append((record.instance_id, Bundle(
            schema="receipts-bundle/1", instance=instance,
            run=BundleRun(
                run_id=run_dir.name,
                executor_kind=record.executor_kind or disclosure["executor_kind"],
                model=disclosure["model"],
                code_version=disclosure.get("code_version", disclosure.get("receipts_version")),
                budgets=result.input.budgets,
            ),
            shipped=ShippedPatch(number=attempt.number, patch=patch, sha256=digest,
                                 filtered_sha256=final.filtered_sha256,
                                 agent_patch=agent_patch, agent_patch_sha256=_sha(agent_patch)),
            claims=BundleClaims(
                gate_status=final.gate_status, failed_predicate_ids=final.failed_predicate_ids,
                claim_audit=final.claim_audit, official_resolved=final.official_resolved,
            ),
        )))
    # Validate all inputs before publishing any bundles.
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for instance_id, bundle in bundles:
        path = out_dir / f"{instance_id}.json"
        path.write_text(json.dumps(bundle.model_dump(mode="json", by_alias=True),
                                   ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        paths.append(path)
    return paths


class _ReplayExecutor:
    """Track forks and preserve published patch bytes on the fresh witness.

    verify_attempt extracts a canonical Git diff from the reconstructed agent
    branch. Its diff receipt still supplies real scope and provenance evidence.
    The witness applies the filtered published text so Git formatting and CRLF
    normalization cannot silently change the patch that is being rechecked.
    """

    def __init__(self, inner: Executor) -> None:
        self.inner = inner
        self.active: dict[str, Branch] = {}
        self.witness_patch: str | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def prepare(self, source: Any) -> Branch:
        branch, cancelled, error = await complete_shielded(self.inner.prepare(source))
        if branch is not None:
            self.active[branch.id] = branch
        if cancelled:
            raise asyncio.CancelledError
        if error is not None:
            raise error
        return branch

    async def fork(self, *args: Any, **kwargs: Any) -> list[Branch]:
        branches, cancelled, error = await complete_shielded(self.inner.fork(*args, **kwargs))
        if branches is not None:
            self.active.update((branch.id, branch) for branch in branches)
        if cancelled:
            raise asyncio.CancelledError
        if error is not None:
            raise error
        return branches

    async def release(self, branch: Branch) -> None:
        await self.inner.release(branch)
        self.active.pop(branch.id, None)

    async def apply_patch(self, branch: Branch, text: str):
        if branch.id == "w1" and self.witness_patch is not None:
            text = self.witness_patch
        return await self.inner.apply_patch(branch, text)

    async def close(self) -> None:
        errors = []
        for branch in reversed(list(self.active.values())):
            try:
                await self.release(branch)
            except Exception as exc:
                errors.append(str(exc))
        # Docker close also removes resources created before prepare/fork returned.
        close = getattr(self.inner, "close", None)
        if close is not None:
            try:
                value = close()
                if inspect.isawaitable(value):
                    await value
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("sandbox cleanup failed: " + "; ".join(errors))


_DIGEST_NAMES = {
    "sha256": "shipped patch",
    "filtered_sha256": "gate's record",
    "agent_patch_sha256": "agent patch",
}


def _color(text: str, code: str) -> str:
    """Colour only on a terminal; NO_COLOR wins, FORCE_COLOR forces."""
    if os.environ.get("NO_COLOR"):
        return text
    if not (sys.stdout.isatty() or os.environ.get("FORCE_COLOR")):
        return text
    return f"\033[{code}m{text}\033[0m"


def _render(value: Any) -> str:
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
        return value[:12] + "..."
    if isinstance(value, dict):
        return ", ".join(f"{_DIGEST_NAMES.get(k, k)} {_render(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "none"
    if isinstance(value, bool):
        return "resolved" if value else "not resolved"
    if value is None:
        return "not recorded"
    return str(value)


def _check(label: str, expected: Any, observed: Any, started: float) -> bool:
    agrees = expected == observed
    elapsed = f"{time.monotonic() - started:.1f}s"
    if agrees:
        mark, verdict = _color("\u2713", "32"), _color("AGREES", "32")
        body = _render(observed)
    else:
        mark, verdict = _color("\u2717", "31"), _color("DISAGREES", "31")
        body = f"receipt says {_render(expected)}; re-run got {_render(observed)}"
    print(f"  {mark} {label:<14} {body}  {verdict}  ({elapsed})")
    return agrees


def _summary(code: int, started: float) -> None:
    if code == 0:
        print("\n" + _color("Every check agrees with the receipt.", "32")
              + f" ({time.monotonic() - started:.0f}s)")
    elif code == 1:
        print("\n" + _color("The receipt does not hold: a check disagrees.", "31"))


def _infra(exc: BaseException) -> int:
    detail = str(exc).strip().splitlines()
    print("Infrastructure failure: " + (detail[0] if detail else type(exc).__name__))
    return 2


class _PatchDisagreement(Exception):
    """The full agent patch does not filter to the published patch under C0."""


async def _replay(bundle: Bundle, make_executor: Callable[[str], Executor], run_dir: Path) -> int:
    executor = None
    code = 2
    try:
        inner = make_executor(f"reverify-{uuid.uuid4().hex[:12]}")
        executor = _ReplayExecutor(shield_cleanup_methods(inner))
        task = to_task(bundle.instance)
        budgets = bundle.run.budgets
        # pilot run_instance doubles the total baseline allowance, guarding each
        # of the first two runs at min(owner's budget, 300s).
        limit = min(budgets.baseline_limit_s // 2, 300)
        executor.run_pytest = baseline_guard(inner.run_pytest, max(limit, 1))
        spec_paths = sorted(set(task.spec_paths).union(n.split("::", 1)[0] for n in task.spec_tests))
        started = time.monotonic()
        base = await executor.prepare(task.source)
        baseline = await establish_baseline(executor, base, task.suite_scope, task.spec_tests,
                                            max(limit, 1) * 2, spec_paths=spec_paths)
        snapshot = await executor.snapshot(base)
        if snapshot.timed_out or snapshot.exit_code != 0 or snapshot.snapshot_sha is None:
            raise RuntimeError("C0 snapshot failed")
        scope = await build_patch_scope(executor, base, snapshot.snapshot_sha)
        baseline = baseline.model_copy(update={"scope": scope})
        checkpoint = await executor.checkpoint(base)
        await executor.release(base)
        print(f"  \u00b7 {'Checkpoint':<14} rebuilt from {task.source.image}  "
              f"({time.monotonic() - started:.1f}s)")

        started = time.monotonic()
        filtered, _ = filter_patch(bundle.shipped.agent_patch, default_protected_modules(),
                                   frozenset(baseline.spec_paths), scope)
        _check("Filter", bundle.shipped.sha256, _sha(filtered), started)
        if filtered != bundle.shipped.patch:
            raise _PatchDisagreement
        (agent,) = await executor.fork(checkpoint, 1, prefix="agent")
        applied = await executor.apply_patch(agent, bundle.shipped.agent_patch)
        if applied.timed_out or applied.exit_code != 0:
            raise RuntimeError("published patch could not be applied: " + applied.stderr_tail)
        started = time.monotonic()
        executor.witness_patch = bundle.shipped.patch
        verified = await verify_attempt(executor, agent, checkpoint, snapshot.snapshot_sha,
                                        task.suite_scope, budgets.verification_timeout_s, 1,
                                        spec_paths=baseline.spec_paths, scope=scope)
        confirmation = None
        if (verified.verification is not None and not verified.verification.timed_out
                and verified.verification.exit_code in (2, 3, 4)):
            confirmation = await confirm_load_failure(executor, checkpoint, filtered,
                                                       task.suite_scope, budgets.verification_timeout_s, 1)
        verdict = evaluate(
            branch_id=agent.id, witness_id=verified.witness.id, baseline=baseline,
            origin=checkpoint.id, receipts=[applied], patch=verified.patch,
            apply=verified.apply, verification=verified.verification,
            filtered_sha256=_sha(filtered), claims=None,
            load_confirmation_apply=confirmation.apply if confirmation else None,
            load_confirmation=confirmation.verification if confirmation else None,
        )
        if verdict.error_kind == "infrastructure" or (
                verified.patch.timed_out or verified.patch.exit_code != 0
                or verified.patch.diff is None
                or verified.apply.timed_out or verified.apply.exit_code != 0
                or verified.verification is None
                or (verified.verification is not None and (
                    verified.verification.timed_out
                    or verified.verification.exit_code not in (0, 1, 2, 3, 4, 5)
                    or (verified.verification.exit_code in (0, 1, 5)
                        and verified.verification.junit is None)))):
            raise RuntimeError(verdict.error or "witness verification failed")
        checks = [
            _check("Witness patch", bundle.shipped.sha256, verified.apply.patch_sha256, started),
            _check("Gate verdict", bundle.claims.gate_status, verdict.status, started),
            _check("Failed checks", sorted(bundle.claims.failed_predicate_ids),
                   sorted(verdict.failed_predicate_ids()), started),
        ]
        await executor.release(verified.witness)
        await executor.release(agent)

        started = time.monotonic()
        official = await grade_patch(executor, checkpoint, bundle.instance, bundle.shipped.patch,
                                      run_dir, "official.log", budgets.verification_timeout_s)
        if official.infra_error or official.cleanup_error:
            raise RuntimeError(official.infra_error or official.cleanup_error)
        checks.append(_check("Official grade", bundle.claims.official_resolved,
                              official.judgement.resolved, started))
        code = 0 if all(checks) else 1
    except _PatchDisagreement:
        code = 1
    except Exception as exc:
        code = _infra(exc)
    finally:
        if executor is not None:
            _, cancelled, error = await complete_shielded(executor.close())
            if cancelled:
                raise asyncio.CancelledError
            if error is not None:
                code = _infra(error)
    return code


async def reverify(
    bundle_path: Path, *, executor: str = "docker",
    make_executor: Callable[[str], Executor] | None = None,
) -> int:
    """Print agreement checks; return 0 for agreement, 1 disagreement, 2 infrastructure."""
    started = time.monotonic()
    try:
        bundle = Bundle.model_validate_json(bundle_path.read_bytes())
        _instance_id(bundle.instance.instance_id)
    except (OSError, ValueError) as exc:
        print(f"Invalid bundle: {exc}")
        return 1
    where = {"docker": "Docker", "tokenfactory": "Nebius Token Factory Sandboxes"}.get(executor, executor)
    if make_executor is not None:
        where = "the given sandbox"
    print(f"Re-verifying {bundle.instance.instance_id} on {where}\n")
    if not _check("Digests", {"sha256": bundle.shipped.sha256,
                              "filtered_sha256": bundle.shipped.filtered_sha256,
                              "agent_patch_sha256": bundle.shipped.agent_patch_sha256},
                  {"sha256": _sha(bundle.shipped.patch),
                   "filtered_sha256": _sha(bundle.shipped.patch),
                   "agent_patch_sha256": _sha(bundle.shipped.agent_patch)}, started):
        _summary(1, started)
        return 1
    with tempfile.TemporaryDirectory(prefix="receipts-reverify-") as temporary:
        root = Path(temporary)
        if make_executor is not None:
            code = await _replay(bundle, make_executor, root / "grade")
            _summary(code, started)
            return code
        api = None
        code = 2
        try:
            if executor == "docker":
                from receipts.cli import docker_ready
                from receipts.sandbox.docker import DockerExecutor

                ready, reason = await docker_ready()
                if not ready:
                    raise RuntimeError(reason)
                make_executor = lambda run_id: DockerExecutor(root / "executor", MemorySink(), run_id)
            elif executor == "tokenfactory":
                from receipts.cli import tokenfactory_executor_factory
                from receipts.sandbox.busybox import load_busybox
                from receipts.sandbox.tokenfactory_api import TokenFactorySandboxApi

                api = TokenFactorySandboxApi.from_env()
                make_executor = tokenfactory_executor_factory(root / "executor", api, load_busybox())
            else:
                raise ValueError(f"unknown executor: {executor}")
            code = await _replay(bundle, make_executor, root / "grade")
        except Exception as exc:
            code = _infra(exc)
        finally:
            if api is not None:
                _, cancelled, error = await complete_shielded(api.aclose())
                if cancelled:
                    raise asyncio.CancelledError
                if error is not None:
                    code = _infra(error)
        _summary(code, started)
        return code
