"""Data models shared by the executor, the gate and (later) the agent.

Everything here is plain data. Nothing here talks to a model or a sandbox.
A Receipt is the executor's record of one action; the model cannot edit it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ReceiptKind = Literal["command", "write", "diff", "apply", "verification"]
FileCategory = Literal[
    "source", "test", "pytest_config", "executable_artifact", "shadow", "reserved",
    "symlink", "other", "outside", "unparseable",
]
PredicateId = Literal[
    "R1_fail_to_pass", "R2_pass_to_pass", "R3_no_shrink", "R4_patch_scope", "R5_provenance", "R6_claim_audit",
    "R7_no_shortcuts", "R8_review",
]
VerdictStatus = Literal["PASS", "REJECTED", "ERROR"]
ClaimAudit = Literal["honest", "unsupported", "contradicted", "understated", "no_claim"]
Outcome = Literal["passed", "failed", "error", "skipped", "missing"]
FAILURE_TEXT_NOT_RECORDED = "(failure text not recorded)"
FAILURE_TEXT_PROMPT_LIMIT = 6_000
_TRUNCATION_MARKER = "[...]"


def tail_truncate(text: str, limit: int) -> str:
    """Keep the diagnostically useful end of text within an exact limit."""
    if len(text) <= limit:
        return text
    if limit <= len(_TRUNCATION_MARKER):
        return text[-limit:] if limit > 0 else ""
    return _TRUNCATION_MARKER + text[-(limit - len(_TRUNCATION_MARKER)):]


def bounded_target_failure_text(
    targets: Sequence[str],
    failure_text: Mapping[str, str],
    limit: int = FAILURE_TEXT_PROMPT_LIMIT,
) -> dict[str, str]:
    """Allocate a shared character budget proportionally across target failures."""
    ordered_targets = list(dict.fromkeys(targets))
    values = [
        failure_text.get(target, FAILURE_TEXT_NOT_RECORDED)
        for target in ordered_targets
    ]
    total = sum(len(value) for value in values)
    if total <= limit:
        return dict(zip(ordered_targets, values, strict=True))
    if limit <= 0:
        return dict.fromkeys(ordered_targets, "")

    quotas = [len(value) * limit // total for value in values]
    remainder = limit - sum(quotas)
    ranked = sorted(
        range(len(values)),
        key=lambda index: (-(len(values[index]) * limit % total), index),
    )
    for index in ranked[:remainder]:
        quotas[index] += 1

    return {
        target: tail_truncate(value, quota)
        for target, value, quota in zip(
            ordered_targets,
            values,
            quotas,
            strict=True,
        )
    }


class Checkpoint(BaseModel):
    """An immutable filesystem state. On Token Factory this is an image uuid."""
    id: str
    parent: str | None = None
    digest: str | None = None


class Branch(BaseModel):
    id: str
    run_id: str
    head: str
    origin: str


class JunitSummary(BaseModel):
    """What a junit xml file says. Node ids are pytest node ids."""
    passed: list[str]
    failed: list[str]
    errors: list[str]
    skipped: list[str]
    collection_errors: list[str] = Field(
        default_factory=list,
        description="test files that failed to import; their tests count as errors but are not collected ids",
    )
    failure_text: dict[str, str] = Field(
        default_factory=dict,
        description="bounded failure diagnostics keyed by test id or collection-error file",
    )

    @property
    def collected(self) -> int:
        return len(self.passed) + len(self.failed) + len(self.errors) + len(self.skipped)

    @property
    def n_passed(self) -> int:
        return len(self.passed)

    @property
    def n_failed(self) -> int:
        return len(self.failed)

    @property
    def n_errors(self) -> int:
        return len(self.errors)

    @property
    def n_skipped(self) -> int:
        return len(self.skipped)

    def all_ids(self) -> set[str]:
        return set(self.passed) | set(self.failed) | set(self.errors) | set(self.skipped)

    def outcome(self, node_id: str) -> Outcome:
        if node_id in self.passed:
            return "passed"
        if node_id in self.failed:
            return "failed"
        if node_id in self.errors:
            return "error"
        if node_id in self.skipped:
            return "skipped"
        if node_id.split("::", 1)[0] in self.collection_errors:
            return "error"
        return "missing"


class ChangedFile(BaseModel):
    path: str
    added: int
    deleted: int
    category: FileCategory
    status: Literal["added", "modified", "deleted"] | None = None


class ShortcutFinding(BaseModel):
    kind: Literal["uncalled_private_helper", "stub"]
    path: str
    name: str | None = None
    line: int | None = None
    detail: str


class DiffSummary(BaseModel):
    files: list[ChangedFile]
    patch_sha256: str
    patch_path: str | None = None
    shortcuts: list[ShortcutFinding] | None = None

    @property
    def changed_lines(self) -> int:
        return sum(f.added + f.deleted for f in self.files)


class Receipt(BaseModel):
    receipt_id: str
    seq: int
    branch_id: str
    kind: ReceiptKind
    cmd: str | None = None
    path: str | None = None
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    stdout_sha256: str | None = None
    log_path: str | None = None
    tree_digest: str | None = None
    tree_download_s: float | None = None
    started_at: datetime
    duration_s: float
    timed_out: bool = False
    image_before: str
    image_after: str
    junit: JunitSummary | None = None
    diff: DiffSummary | None = None
    patch_sha256: str | None = None
    dropped_paths: list[str] = Field(default_factory=list)
    snapshot_sha: str | None = None


class PatchScope(BaseModel):
    protected_names: list[str]
    c0_top_level: list[str]


class Baseline(BaseModel):
    """The suite as it stood before any agent touched the repo."""
    runs: list[JunitSummary]
    run_receipt_ids: list[str] = Field(description="receipt ids of the baseline runs, for provenance")
    collected_ids: list[str] = Field(description="every node id seen in any baseline run")
    skipped_ids: list[str] = Field(description="node ids skipped in any baseline run")
    protected: list[str] = Field(description="node ids that passed in every baseline run")
    unstable: list[str] = Field(description="node ids whose outcome differed between runs")
    target: list[str] = Field(description="node ids that must go from failing to passing")
    target_failure_text: dict[str, str] = Field(
        default_factory=dict,
        description="first-run failure diagnostics for each mapped target id",
    )
    target_map: dict[str, list[str]] = Field(
        default_factory=dict,
        description="dataset target ids mapped to the full collected pytest node ids",
    )
    spec_paths: list[str] = Field(
        default_factory=list,
        description=(
            "repository-relative paths of the specification "
            "(the test patch and the spec tests' files); read-only"
        ),
    )
    scope: PatchScope | None = None


class Claims(BaseModel):
    """What the worker said when it called finish. Audited, never trusted."""
    tests_run: bool
    target_tests_pass: bool
    full_suite_pass: bool
    files_changed: list[str]


class PredicateResult(BaseModel):
    id: PredicateId
    passed: bool
    evidence: str


class Verdict(BaseModel):
    branch_id: str
    status: VerdictStatus
    predicates: list[PredicateResult]
    claim_audit: ClaimAudit
    claim_evidence: str
    error: str | None = None
    error_kind: Literal["attempt", "infrastructure"] | None = None

    def failed_predicate_ids(self) -> list[str]:
        """Failed deciding predicates: R1 to R5, R7 and R8. R6 is advisory."""
        return [p.id for p in self.predicates if not p.passed and p.id != "R6_claim_audit"]
