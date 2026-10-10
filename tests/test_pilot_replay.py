from __future__ import annotations

import hashlib
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from receipts.agent.planner import Plan
from receipts.agent.worker import WorkerOutcome
from receipts.models import (
    Baseline,
    Checkpoint,
    Claims,
    DiffSummary,
    JunitSummary,
    PredicateResult,
    Receipt,
    Verdict,
)
from receipts.orchestrate import (
    AttemptResult,
    Disclosure,
    RunBudgets,
    RunInput,
    RunResult,
)
from receipts.patchscope import summarize_patch
from receipts.pilot.runner import (
    AttemptRecord,
    FinalRecord,
    InstanceRecord,
    PilotCost,
)


TARGET = "tests/test_spec.py::test_target"
PROTECTED = "tests/test_existing.py::test_ok"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)

ADDED_SCRATCH_TEST = """\
diff --git a/debug_test.py b/debug_test.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/debug_test.py
@@ -0,0 +1 @@
+def test_debug(): pass
"""

SOURCE_EDIT = """\
diff --git a/src/pkg/core.py b/src/pkg/core.py
index 1111111..2222222 100644
--- a/src/pkg/core.py
+++ b/src/pkg/core.py
@@ -1 +1 @@
-old = True
+old = False
"""

ROOT_PACKAGE_COPY = SOURCE_EDIT + """\
diff --git a/pkg/__init__.py b/pkg/__init__.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/pkg/__init__.py
@@ -0,0 +1 @@
+from src.pkg import *
"""

SPEC_EDIT = """\
diff --git a/specs/contract.txt b/specs/contract.txt
index 1111111..2222222 100644
--- a/specs/contract.txt
+++ b/specs/contract.txt
@@ -1 +1 @@
-old contract
+new contract
"""

ROOT_STEM_SHADOW = """\
diff --git a/tool.cfg b/tool.cfg
index 1111111..2222222 100644
--- a/tool.cfg
+++ b/tool.cfg
@@ -1 +1 @@
-old = true
+old = false
diff --git a/tool.py b/tool.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/tool.py
@@ -0,0 +1 @@
+value = 1
"""

SPEC_TEST_PATCH = """\
diff --git a/tests/test_spec.py b/tests/test_spec.py
new file mode 100644
index 0000000..4444444
--- /dev/null
+++ b/tests/test_spec.py
@@ -0,0 +1 @@
+def test_target(): pass
"""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _v1_verdict(status: str, failed: list[str]) -> Verdict:
    predicates = [
        PredicateResult(
            id=predicate_id,
            passed=False,
            evidence="v1 failure",
        )
        for predicate_id in failed
    ]
    return Verdict(
        branch_id="agent1",
        status=status,
        predicates=predicates,
        claim_audit="no_claim",
        claim_evidence="branch ended without a finish call",
        error="v1 gate error" if status == "ERROR" else None,
    )


def _write_fixture(
    repo_root: Path,
    *,
    collection: Path = Path("pilot/unit"),
    instance_id: str = "fixture__project-1",
    patch_text: str,
    filtered_text: str | None = None,
    test_patch: str = SPEC_TEST_PATCH,
    v1_status: str,
    v1_failed: list[str],
    official_resolved: bool | None = True,
    verification_exit: int = 0,
    record_run_dir: str | None = None,
    receipt_patch_sha256: str | None = None,
) -> tuple[Path, Path]:
    filtered_text = patch_text if filtered_text is None else filtered_text
    collection_dir = repo_root / collection
    record_dir = collection_dir / instance_id
    run_dir = record_dir / "runs" / "run-1"
    attempt_dir = run_dir / "attempts" / "1"
    witness_dir = attempt_dir / "witness"
    agent_dir = run_dir / "agent"
    witness_dir.mkdir(parents=True)
    agent_dir.mkdir()

    baseline_run = JunitSummary(
        passed=[PROTECTED],
        failed=[TARGET],
        errors=[],
        skipped=[],
    )
    baseline = Baseline(
        runs=[baseline_run, baseline_run],
        run_receipt_ids=["base-1", "base-2"],
        collected_ids=[TARGET, PROTECTED],
        skipped_ids=[],
        protected=[PROTECTED],
        unstable=[],
        target=[TARGET],
    )
    (run_dir / "baseline.json").write_text(
        baseline.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    old_summary = summarize_patch(patch_text)
    old_summary = DiffSummary(
        files=[
            changed.model_copy(update={"status": None})
            for changed in old_summary.files
        ],
        patch_sha256=receipt_patch_sha256 or old_summary.patch_sha256,
        patch_path="/old/artifacts/agent1-1.patch",
    )
    patch = Receipt(
        receipt_id="agent1-1",
        seq=1,
        branch_id="agent1",
        kind="diff",
        exit_code=0,
        started_at=NOW,
        duration_s=0.1,
        image_before="c0",
        image_after="agent-image-1",
        diff=old_summary,
    )
    (agent_dir / "receipts.jsonl").write_text(
        patch.model_dump_json() + "\n",
        encoding="utf-8",
    )

    apply = Receipt(
        receipt_id="w1-1",
        seq=1,
        branch_id="w1",
        kind="apply",
        exit_code=0,
        started_at=NOW,
        duration_s=0.1,
        image_before="c0",
        image_after="witness-image-1",
        patch_sha256=_sha(filtered_text),
    )
    verification = Receipt(
        receipt_id="w1-2",
        seq=2,
        branch_id="w1",
        kind="verification",
        exit_code=verification_exit,
        stdout_tail="pytest could not load" if verification_exit in (2, 3, 4) else "",
        started_at=NOW,
        duration_s=0.2,
        image_before="witness-image-1",
        image_after="witness-image-2",
        junit=(
            None
            if verification_exit in (2, 3, 4)
            else JunitSummary(
                passed=[TARGET, PROTECTED],
                failed=[],
                errors=[],
                skipped=[],
            )
        ),
    )
    (witness_dir / "receipts.jsonl").write_text(
        apply.model_dump_json() + "\n" + verification.model_dump_json() + "\n",
        encoding="utf-8",
    )

    v1_verdict = _v1_verdict(v1_status, v1_failed)
    worker = WorkerOutcome(
        end="finished",
        claims=None,
        summary="fixture attempt",
        turns=1,
        receipt_ids=[],
    )
    attempt = AttemptResult(
        number=1,
        worker=worker,
        verdict=v1_verdict,
        patch_path="attempts/1/patch.diff",
        filtered_patch_path="attempts/1/filtered.diff",
        witness_branch_id="w1",
        dropped_paths=[],
    )
    result = RunResult(
        input=RunInput(
            source={"image": "fixture:latest"},
            issue="fixture issue",
            spec_tests=[TARGET],
            suite_scope="tests",
            appeals=1,
            budgets=RunBudgets(),
        ),
        baseline=baseline,
        plan=Plan(
            hypothesis="fixture",
            files_to_edit=["src/pkg/core.py"],
            approach="fixture",
        ),
        attempts=[attempt],
        final_verdict=v1_verdict,
        verdict_history=[v1_verdict],
        selected_patch_path=(
            "attempts/1/filtered.diff" if v1_status == "PASS" else None
        ),
        verified_fix=v1_status == "PASS",
        cost={},
        wall_time_s=1.0,
        disclosure=Disclosure(
            model={},
            receipts_version="0.0.1",
            executor_kind="fixture",
            test_digests={},
            pytest_config_digests={},
            lock_sha256="lock",
        ),
        snapshot_receipt_id="base-2",
        checkpoint=Checkpoint(id="c0"),
        checkpoint_id="c0",
        agent_branch_id="agent1",
    )
    (run_dir / "result.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (attempt_dir / "patch.diff").write_text(patch_text, encoding="utf-8")
    (attempt_dir / "filtered.diff").write_text(filtered_text, encoding="utf-8")
    (attempt_dir / "verdict.json").write_text(
        v1_verdict.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    record_attempt = AttemptRecord(
        end="finished",
        claimed_done=False,
        claims=None,
        naive_green=False,
        gate_status=v1_status,
        failed_predicate_ids=v1_failed,
        claim_audit="no_claim",
        official_resolved=official_resolved,
        agreement=None,
        filtered_patch_sha256=_sha(filtered_text),
        gate_error="v1 gate error" if v1_status == "ERROR" else None,
    )
    record = InstanceRecord(
        instance_id=instance_id,
        status="ran",
        reason=None,
        run_dir=(
            record_run_dir
            if record_run_dir is not None
            else str(collection / instance_id / "runs" / "run-1")
        ),
        attempts=[record_attempt],
        final=FinalRecord(
            gate_status=v1_status,
            verified_fix=v1_status == "PASS",
            official_resolved=official_resolved,
        ),
        cost=PilotCost(tokens=0),
        wall_time_s=1.0,
    )
    record_dir.mkdir(parents=True, exist_ok=True)
    (record_dir / "record.json").write_text(
        record.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    data_path = repo_root / f"{collection_dir.name}-data.jsonl"
    data_path.write_text(
        json.dumps(
            {
                "instance_id": instance_id,
                "repo": "fixture/project",
                "base_commit": "abc123",
                "image_name": "fixture:latest",
                "test_patch": test_patch,
                "FAIL_TO_PASS": [TARGET],
                "PASS_TO_PASS": [PROTECTED],
                "test_cmd": "pytest tests",
                "problem_statement": "fixture issue",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    return collection_dir, data_path


def _replay_module():
    return importlib.import_module("receipts.pilot.replay")


def _build_fixture_replay(
    tmp_path: Path,
    monkeypatch,
    **fixture_kwargs,
):
    replay = _replay_module()
    monkeypatch.setattr(replay, "_REPOSITORY_ROOT", tmp_path)
    collection, data_path = _write_fixture(tmp_path, **fixture_kwargs)
    return replay.build_replay([collection], data_path)


def test_added_scratch_test_rejected_by_v1_becomes_pass(
    tmp_path: Path,
    monkeypatch,
):
    report = _build_fixture_replay(
        tmp_path,
        monkeypatch,
        patch_text=ADDED_SCRATCH_TEST,
        filtered_text="",
        v1_status="REJECTED",
        v1_failed=["R4_patch_scope"],
    )

    row = report.attempts[0]
    assert row.v1_status == "REJECTED"
    assert row.v2_status == "PASS"
    assert row.v2_failed_predicate_ids == []
    assert row.scope == "inferred"
    assert row.status_changed is True
    assert [item.instance_id for item in report.summary.became_pass] == [
        "fixture__project-1",
    ]


def test_exit_four_becomes_rejected_with_assumed_confirmation(
    tmp_path: Path,
    monkeypatch,
):
    report = _build_fixture_replay(
        tmp_path,
        monkeypatch,
        patch_text=SOURCE_EDIT,
        v1_status="ERROR",
        v1_failed=[],
        verification_exit=4,
    )

    row = report.attempts[0]
    assert row.v2_status == "REJECTED"
    assert row.load_failure == "assumed reproduced"
    assert row.v2_failed_predicate_ids == [
        "R1_fail_to_pass",
        "R2_pass_to_pass",
        "R3_no_shrink",
    ]
    assert report.summary.stopped_being_error == [row]


def test_root_copy_of_src_package_is_rejected_as_a_shadow(
    tmp_path: Path,
    monkeypatch,
):
    report = _build_fixture_replay(
        tmp_path,
        monkeypatch,
        patch_text=ROOT_PACKAGE_COPY,
        v1_status="PASS",
        v1_failed=[],
    )

    row = report.attempts[0]
    assert row.v2_status == "REJECTED"
    assert row.v2_failed_predicate_ids == ["R4_patch_scope"]


def test_edit_to_dataset_spec_path_is_rejected(
    tmp_path: Path,
    monkeypatch,
):
    report = _build_fixture_replay(
        tmp_path,
        monkeypatch,
        patch_text=SPEC_EDIT,
        test_patch=SPEC_EDIT,
        v1_status="PASS",
        v1_failed=[],
    )

    row = report.attempts[0]
    assert row.v2_status == "REJECTED"
    assert row.v2_failed_predicate_ids == ["R4_patch_scope"]


def test_new_gate_looser_writes_blocker_outputs_and_cli_exits_one(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    import receipts.cli as cli

    replay = _replay_module()
    monkeypatch.setattr(replay, "_REPOSITORY_ROOT", tmp_path)
    collection, data_path = _write_fixture(
        tmp_path,
        patch_text=ADDED_SCRATCH_TEST,
        filtered_text="",
        v1_status="REJECTED",
        v1_failed=["R4_patch_scope"],
        official_resolved=False,
    )
    output_prefix = tmp_path / "outputs" / "replay"

    status = cli.main(
        [
            "pilot",
            "replay",
            str(collection),
            "--data",
            str(data_path),
            "--out",
            str(output_prefix),
        ],
    )

    payload = json.loads(
        Path(f"{output_prefix}.json").read_text(encoding="utf-8"),
    )
    markdown = Path(f"{output_prefix}.md").read_text(encoding="utf-8")
    assert status == 1
    assert "run_dir" not in payload["attempts"][0]
    assert len(payload["summary"]["new_gate_looser"]) == 1
    assert markdown.splitlines()[0] == "# BLOCKER: 1 NEW gate-looser attempt"
    assert "scope is inferred" in markdown
    assert "B2 confirmations are assumed" in markdown
    assert "new_gate_looser=1" in capsys.readouterr().out


def test_absolute_old_record_run_dir_resolves_from_pilot_under_repo_root(
    tmp_path: Path,
    monkeypatch,
):
    old_run_dir = (
        "/Users/sunzeyu/Documents/nebius-hackathon/"
        "pilot/absolute/fixture__project-1/runs/run-1"
    )
    report = _build_fixture_replay(
        tmp_path,
        monkeypatch,
        collection=Path("pilot/absolute"),
        patch_text=SOURCE_EDIT,
        v1_status="PASS",
        v1_failed=[],
        record_run_dir=old_run_dir,
    )

    assert report.attempts[0].v2_status == "PASS"


def test_patch_receipt_is_selected_by_attempt_order_after_text_normalization(
    tmp_path: Path,
    monkeypatch,
):
    report = _build_fixture_replay(
        tmp_path,
        monkeypatch,
        patch_text=SOURCE_EDIT,
        v1_status="PASS",
        v1_failed=[],
        receipt_patch_sha256="0" * 64,
    )

    assert report.attempts[0].v2_status == "PASS"


def test_record_selected_directory_resolves_stale_relative_launch_path(
    tmp_path: Path,
    monkeypatch,
):
    report = _build_fixture_replay(
        tmp_path,
        monkeypatch,
        collection=Path("pilot/published-launch"),
        patch_text=SOURCE_EDIT,
        v1_status="PASS",
        v1_failed=[],
        record_run_dir=(
            "pilot/original-launch/fixture__project-1/runs/run-1"
        ),
    )

    assert report.attempts[0].v2_status == "PASS"


def test_inferred_scope_protects_the_stem_of_each_c0_entry(
    tmp_path: Path,
    monkeypatch,
):
    report = _build_fixture_replay(
        tmp_path,
        monkeypatch,
        patch_text=ROOT_STEM_SHADOW,
        v1_status="PASS",
        v1_failed=[],
    )

    assert report.attempts[0].v2_status == "REJECTED"
    assert report.attempts[0].v2_failed_predicate_ids == ["R4_patch_scope"]


def test_real_v1_replay_matches_reviewed_counterfactual_expectations():
    repo_root = Path(__file__).resolve().parents[1]
    launch_3 = repo_root / "pilot" / "run-2026-10-01c"
    launch_2 = repo_root / "pilot" / "aborted-2026-10-01-launch2"
    data_path = repo_root / "data" / "rebench-v2-python.jsonl"
    if not (launch_3.is_dir() and launch_2.is_dir()):
        pytest.skip("published v1 pilot evidence is absent")
    if not data_path.is_file():
        pytest.skip("the SWE-rebench-V2 extract data/rebench-v2-python.jsonl is absent (not committed)")

    replay = _replay_module()
    report = replay.build_replay([launch_3, launch_2], data_path)

    by_key = {
        (row.record_set, row.instance_id, row.attempt): row
        for row in report.attempts
    }
    for instance_id, attempt in (
        ("aio-libs__aiohttp-8823", 1),
        ("meltano__sdk-3020", 2),
        ("pandas-dev__pandas-56926", 2),
        ("sparckles__robyn-1002", 1),
    ):
        row = by_key[("run-2026-10-01c", instance_id, attempt)]
        assert row.v1_status == "REJECTED"
        assert row.v2_status == "PASS"

    vyper = by_key[("run-2026-10-01c", "vyperlang__vyper-3261", 1)]
    assert vyper.v2_status == "REJECTED"
    assert vyper.load_failure == "assumed reproduced"

    for record_set in (
        "run-2026-10-01c",
        "aborted-2026-10-01-launch2",
    ):
        scikit = by_key[
            (record_set, "scikit-build__scikit-build-core-254", 1)
        ]
        assert scikit.v2_status == "REJECTED"
        assert "R4_patch_scope" in scikit.v2_failed_predicate_ids

    assert report.summary.new_gate_looser == []
    pypdf = by_key[("run-2026-10-01c", "py-pdf__pypdf2-1318", 2)]
    assert pypdf.v1_status == "PASS"
    assert pypdf.v2_status == "PASS"
    assert pypdf.official_resolved is False
    assert pypdf in report.summary.pre_existing_unresolved_pass
