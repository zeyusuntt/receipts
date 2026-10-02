"""The executor's own baseline and witness verification runs.

The worker's pytest runs on the agent branch are feedback for the model. The
gate believes only canonical verification on a fresh witness forked from C0.
"""

from __future__ import annotations

import hashlib
import shlex
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from receipts.models import (
    FAILURE_TEXT_NOT_RECORDED,
    Baseline,
    Branch,
    Checkpoint,
    JunitSummary,
    PatchScope,
    Receipt,
)
from receipts.patchscope import default_protected_modules, filter_patch
from receipts.sandbox.protocol import CheckpointTampered, Executor
from receipts.verify.targets import map_target_ids


class Attempt(BaseModel):
    patch: Receipt
    filtered_patch: str
    filtered_sha256: str
    dropped: list[str]
    witness: Branch
    witness_provisioned: bool
    apply: Receipt
    verification: Receipt | None


class LoadConfirmation(BaseModel):
    attempt: int
    branch: Branch
    apply: Receipt
    verification: Receipt | None


class TargetNotFailing(Exception):
    def __init__(
        self,
        node_ids: list[str],
        target_map: dict[str, list[str]] | None = None,
    ) -> None:
        self.node_ids = list(node_ids)
        self.target_map = {
            node_id: list(mapped)
            for node_id, mapped in (target_map or {}).items()
        }
        details = (
            "; ".join(
                f"{node_id} -> {self.target_map[node_id]}"
                for node_id in self.node_ids
            )
            if self.target_map
            else str(self.node_ids)
        )
        super().__init__(
            "target tests did not fail in every baseline run: " + details,
        )


class BaselineTooSlow(Exception):
    def __init__(self, seconds: float) -> None:
        super().__init__(f"baseline suite took {seconds:.0f}s, over the limit")
        self.seconds = seconds


class BaselineBroken(Exception):
    pass


async def _checkpoint_error_attempt(
    ex: Executor,
    agent: Branch,
    c0: Checkpoint,
    attempt: int,
    error: CheckpointTampered,
    patch: Receipt | None,
    filtered_patch: str,
    filtered_sha256: str,
    dropped: list[str],
) -> Attempt:
    if patch is None:
        patch = error.patch_receipt
    if patch is None:
        raise RuntimeError("checkpoint tampering was raised without a patch receipt")
    witness = Branch(id=f"w{attempt}", run_id=agent.run_id, head=c0.id, origin=c0.id)
    apply = await ex.apply_patch(witness, filtered_patch)
    if apply.exit_code != 1 or apply.stderr_tail != str(error):
        raise RuntimeError("executor did not preserve the checkpoint tampering failure")
    return Attempt(
        patch=patch,
        filtered_patch=filtered_patch,
        filtered_sha256=filtered_sha256,
        dropped=dropped,
        witness=witness,
        witness_provisioned=False,
        apply=apply,
        verification=None,
    )


async def establish_baseline(
    ex: Executor,
    base: Branch,
    suite_scope: str,
    target: list[str],
    limit_s: int,
    spec_paths: Sequence[str] = (),
) -> Baseline:
    first = await ex.run_pytest(base, suite_scope, timeout_s=max(limit_s, 1))
    if first.timed_out or first.duration_s > limit_s:
        raise BaselineTooSlow(first.duration_s)
    if first.exit_code not in (0, 1, 5) or first.junit is None:
        raise BaselineBroken(f"first baseline run is not a valid pytest run (exit {first.exit_code}, junit={'present' if first.junit else 'missing'})")
    receipts = [first]
    if first.duration_s < limit_s / 2:
        second = await ex.run_pytest(base, suite_scope, timeout_s=limit_s)
        if second.timed_out or second.exit_code not in (0, 1, 5) or second.junit is None:
            raise BaselineBroken(f"second baseline run failed (timed_out={second.timed_out}, exit {second.exit_code})")
        receipts.append(second)
    runs: list[JunitSummary] = [r.junit for r in receipts]  # type: ignore[misc]

    seen = sorted(set().union(*(j.all_ids() for j in runs)))
    target_map = map_target_ids(target, seen)
    mapped_target = list(
        dict.fromkeys(
            node_id
            for dataset_id in target
            for node_id in target_map[dataset_id]
        ),
    )

    # Every mapped target must be failed or errored in every run; anything else
    # cannot anchor a verdict. Keep dataset ids on the exception for screening.
    bad_targets = [
        dataset_id
        for dataset_id in target
        if any(
            any(j.outcome(node_id) not in ("failed", "error") for j in runs)
            for node_id in target_map[dataset_id]
        )
    ]
    if bad_targets:
        raise TargetNotFailing(
            bad_targets,
            {dataset_id: target_map[dataset_id] for dataset_id in bad_targets},
        )

    unstable = sorted(n for n in seen if len({j.outcome(n) for j in runs}) > 1)
    protected = sorted(n for n in seen if all(j.outcome(n) == "passed" for j in runs))
    skipped = sorted(n for n in seen if any(j.outcome(n) == "skipped" for j in runs))
    first_summary = runs[0]
    target_failure_text: dict[str, str] = {}
    for node_id in mapped_target:
        text = first_summary.failure_text.get(node_id)
        if not text and node_id not in first_summary.all_ids():
            file_path = node_id.split("::", 1)[0]
            if file_path in first_summary.collection_errors:
                text = first_summary.failure_text.get(file_path)
        target_failure_text[node_id] = (
            text if text else FAILURE_TEXT_NOT_RECORDED
        )
    return Baseline(runs=runs, run_receipt_ids=[r.receipt_id for r in receipts], collected_ids=seen,
                    skipped_ids=skipped, protected=protected, unstable=unstable, target=mapped_target,
                    target_failure_text=target_failure_text,
                    target_map=target_map,
                    spec_paths=sorted(set(spec_paths)))


async def verify_attempt(ex: Executor, agent: Branch, c0: Checkpoint, snapshot_sha: str,
                         suite_scope: str, timeout_s: int, attempt: int,
                         spec_paths: Sequence[str] = (),
                         scope: PatchScope | None = None) -> Attempt:
    patch = None
    patch_text = ""
    filtered_patch = ""
    dropped: list[str] = []
    filtered_sha256 = hashlib.sha256(b"").hexdigest()

    try:
        patch = await ex.patch(agent, snapshot_sha)
        if patch.exit_code == 0 and patch.diff is not None and patch.diff.patch_path is not None:
            patch_text = Path(patch.diff.patch_path).read_text()
        protected_modules = default_protected_modules()
        filtered_patch, dropped = filter_patch(
            patch_text,
            protected_modules,
            frozenset(spec_paths),
            scope,
        )
        filtered_sha256 = hashlib.sha256(filtered_patch.encode()).hexdigest()
        (witness,) = await ex.fork(c0, 1, prefix="w")
    except CheckpointTampered as error:
        return await _checkpoint_error_attempt(
            ex,
            agent,
            c0,
            attempt,
            error,
            patch,
            filtered_patch,
            filtered_sha256,
            dropped,
        )
    if witness.id != f"w{attempt}":
        raise RuntimeError(f"witness sequence mismatch: expected w{attempt}, got {witness.id}")
    apply = await ex.apply_patch(witness, filtered_patch)
    verification = None
    if apply.exit_code == 0:
        verification = await ex.run_pytest(witness, suite_scope, timeout_s=timeout_s, kind="verification")
    return Attempt(patch=patch, filtered_patch=filtered_patch, filtered_sha256=filtered_sha256,
                   dropped=dropped, witness=witness, witness_provisioned=True,
                   apply=apply, verification=verification)


async def confirm_load_failure(
    ex: Executor,
    c0: Checkpoint,
    filtered_patch: str,
    suite_scope: str,
    timeout_s: int,
    attempt: int,
) -> LoadConfirmation:
    (branch,) = await ex.fork(c0, 1, prefix="c")
    try:
        applied = await ex.apply_patch(branch, filtered_patch)
        verification = None
        if applied.exit_code == 0:
            verification = await ex.run_pytest(
                branch,
                suite_scope,
                timeout_s=timeout_s,
                kind="verification",
            )
        return LoadConfirmation(
            attempt=attempt,
            branch=branch,
            apply=applied,
            verification=verification,
        )
    finally:
        await ex.release(branch)


async def rerun_one(ex: Executor, witness: Branch, node_id: str, timeout_s: int) -> Receipt:
    return await ex.run_pytest(witness, shlex.quote(node_id), timeout_s=timeout_s, kind="verification")
