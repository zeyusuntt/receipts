"""Data models shared by the executor, the gate and (later) the agent.

Everything here is plain data. Nothing here talks to a model or a sandbox.
A Receipt is the executor's record of one action; the model cannot edit it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ReceiptKind = Literal["command", "write", "diff", "apply", "verification"]
FileCategory = Literal[
    "source", "test", "pytest_config", "executable_artifact", "shadow",
    "symlink", "other", "outside", "unparseable",
]
PredicateId = Literal[
    "R1_fail_to_pass", "R2_pass_to_pass", "R3_no_shrink", "R4_patch_scope", "R5_provenance", "R6_claim_audit",
]
VerdictStatus = Literal["PASS", "REJECTED", "ERROR"]
ClaimAudit = Literal["honest", "unsupported", "contradicted", "understated", "no_claim"]
Outcome = Literal["passed", "failed", "error", "skipped", "missing"]


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


class DiffSummary(BaseModel):
    files: list[ChangedFile]
    patch_sha256: str
    patch_path: str | None = None

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


class Baseline(BaseModel):
    """The suite as it stood before any agent touched the repo."""
    runs: list[JunitSummary]
    run_receipt_ids: list[str] = Field(description="receipt ids of the baseline runs, for provenance")
    collected_ids: list[str] = Field(description="every node id seen in any baseline run")
    skipped_ids: list[str] = Field(description="node ids skipped in any baseline run")
    protected: list[str] = Field(description="node ids that passed in every baseline run")
    unstable: list[str] = Field(description="node ids whose outcome differed between runs")
    target: list[str] = Field(description="node ids that must go from failing to passing")


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

    def failed_predicate_ids(self) -> list[str]:
        """Failed gating predicates, R1 to R5. R6 is advisory and never listed here."""
        return [p.id for p in self.predicates if not p.passed and p.id != "R6_claim_audit"]
