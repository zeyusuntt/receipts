from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from receipts.models import Branch, Checkpoint, JunitSummary, Receipt
from receipts.pilot import grade as pilot_grade
from receipts.swerebench import Instance, OfficialJudgement


TARGET = "tests/test_calc.py::test_sub"
PROTECTED = "tests/test_calc.py::test_add"


def _screen_module():
    try:
        return importlib.import_module("receipts.pilot.screen")
    except ModuleNotFoundError:
        pytest.fail("receipts.pilot.screen is missing")


def _instance(instance_id: str) -> Instance:
    return Instance(
        instance_id=instance_id,
        repo="fixture/calc",
        base_commit="HEAD",
        image_name=instance_id,
        test_patch="",
        fail_to_pass=[TARGET],
        pass_to_pass=[PROTECTED],
        test_cmd="pytest tests -rA",
        problem_statement="Fix subtraction without breaking addition.",
    )


def _official_record(*, infra_error: str | None = None):
    from receipts.pilot.grade import OfficialRecord

    return OfficialRecord(
        attempt=0,
        branch_id="official1",
        apply_exit_code=0,
        test_exit_code=0,
        timed_out=False,
        log_path="official.log",
        log_sha256=hashlib.sha256(b"").hexdigest(),
        judgement=OfficialJudgement(
            resolved=False,
            from_fail_to_pass=[],
            failed_from_fail_to_pass=[TARGET],
            failed_from_pass_to_pass=[],
        ),
        infra_error=infra_error,
        applied_sha256=hashlib.sha256(b"").hexdigest(),
        read_sha256=hashlib.sha256(b"").hexdigest(),
    )


@pytest.mark.parametrize(
    ("log_text", "infra_error", "gradeable", "failing", "passing"),
    [
        (
            f"FAILED {TARGET}\nPASSED {PROTECTED}\n",
            None,
            True,
            [],
            [],
        ),
        (
            f"FAILED {TARGET}\nFAILED {PROTECTED}\n",
            None,
            False,
            [PROTECTED],
            [],
        ),
        (
            f"PASSED {TARGET}\nPASSED {PROTECTED}\n",
            None,
            False,
            [],
            [TARGET],
        ),
        (
            f"FAILED {TARGET}\nPASSED {PROTECTED}\n",
            "full log unavailable",
            False,
            [],
            [],
        ),
    ],
)
def test_gradeability_uses_exact_official_ids(
    log_text: str,
    infra_error: str | None,
    gradeable: bool,
    failing: list[str],
    passing: list[str],
):
    result = pilot_grade.gradeability(
        _instance("candidate"),
        _official_record(infra_error=infra_error),
        log_text,
    )

    assert result.gradeable is gradeable
    assert result.failing_pass_to_pass == failing
    assert result.passing_fail_to_pass == passing
    assert result.infra_error == infra_error


class _FakeScreenFactory:
    def __init__(
        self,
        root: Path,
        plans: dict[str, list[str]],
        delays: dict[str, float] | None = None,
    ) -> None:
        self.root = root
        self.plans = plans
        self.delays = delays or {}
        self.created: dict[str, int] = {}
        self.active = 0
        self.max_active = 0

    def __call__(self, run_id: str):
        instance_id = next(
            instance_id
            for instance_id in sorted(self.plans, key=len, reverse=True)
            if instance_id in run_id
        )
        index = self.created.get(instance_id, 0)
        scenarios = self.plans[instance_id]
        scenario = scenarios[min(index, len(scenarios) - 1)]
        self.created[instance_id] = index + 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        return _FakeScreenExecutor(
            self,
            self.root / run_id,
            run_id,
            scenario,
            self.delays.get(instance_id, 0),
        )


class _FakeScreenExecutor:
    def __init__(
        self,
        factory: _FakeScreenFactory,
        root: Path,
        run_id: str,
        scenario: str,
        delay: float,
    ) -> None:
        self.factory = factory
        self.root = root
        self.run_id = run_id
        self.scenario = scenario
        self.delay = delay
        self.root.mkdir(parents=True, exist_ok=True)
        self.released: list[str] = []
        self.closed = False
        self._seq: dict[str, int] = {}

    def _receipt(self, branch: Branch, **fields) -> Receipt:
        seq = self._seq.get(branch.id, 0) + 1
        self._seq[branch.id] = seq
        before = branch.head
        branch.head = f"{branch.id}-image-{seq}"
        return Receipt(
            receipt_id=f"{branch.id}-{seq}",
            seq=seq,
            branch_id=branch.id,
            started_at=datetime.now(timezone.utc),
            duration_s=0.01,
            image_before=before,
            image_after=branch.head,
            **fields,
        )

    async def prepare(self, source) -> Branch:
        return Branch(id="base", run_id=self.run_id, head="base-image", origin="base-image")

    async def run_pytest(
        self,
        branch: Branch,
        args: str,
        timeout_s: int,
        kind: str = "command",
    ) -> Receipt:
        target_passes = self.scenario == "rule4"
        junit = JunitSummary(
            passed=[PROTECTED, TARGET] if target_passes else [PROTECTED],
            failed=[] if target_passes else [TARGET],
            errors=[],
            skipped=[],
        )
        return self._receipt(
            branch,
            kind=kind,
            cmd=args,
            exit_code=1 if junit.failed else 0,
            stdout_tail="",
            timed_out=False,
            junit=junit,
        )

    async def snapshot(self, branch: Branch) -> Receipt:
        return self._receipt(
            branch,
            kind="command",
            cmd="snapshot",
            exit_code=0,
            stdout_tail="snapshot\n",
            timed_out=False,
            snapshot_sha="snapshot-sha",
        )

    async def checkpoint(self, branch: Branch) -> Checkpoint:
        return Checkpoint(id="checkpoint", parent=branch.head, digest="digest")

    async def fork(self, checkpoint: Checkpoint, n: int, prefix: str = "b"):
        assert n == 1
        return [
            Branch(
                id=f"{prefix}1",
                run_id=self.run_id,
                head=checkpoint.id,
                origin=checkpoint.id,
            ),
        ]

    async def apply_patch(self, branch: Branch, patch_text: str) -> Receipt:
        digest = hashlib.sha256(patch_text.encode()).hexdigest()
        return self._receipt(
            branch,
            kind="apply",
            exit_code=0,
            stdout_tail="",
            timed_out=False,
            patch_sha256=digest,
        )

    async def run(self, branch: Branch, cmd: str, timeout_s: int) -> Receipt:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.scenario == "infra":
            log_path = None
            output = f"FAILED {TARGET}\nPASSED {PROTECTED}\n"
        elif self.scenario == "rule5":
            output = f"FAILED {TARGET}\nFAILED {PROTECTED}\n"
            log_path = self.root / "official-source.log"
            log_path.write_text(output, encoding="utf-8")
        else:
            output = f"FAILED {TARGET}\nPASSED {PROTECTED}\n"
            log_path = self.root / "official-source.log"
            log_path.write_text(output, encoding="utf-8")
        return self._receipt(
            branch,
            kind="command",
            cmd=cmd,
            exit_code=0,
            stdout_tail=output,
            stdout_sha256=hashlib.sha256(output.encode()).hexdigest(),
            log_path=str(log_path) if log_path is not None else None,
            timed_out=False,
        )

    async def release(self, branch: Branch) -> None:
        self.released.append(branch.id)

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.factory.active -= 1

    def sandbox_usage(self) -> list[dict]:
        return [
            {
                "sandbox_id": self.run_id,
                "seconds": 1.5,
                "resources": {"cpu": 2, "memory": 2, "disk": 5},
            },
        ]


def _read_ledger(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def test_screen_applies_rules_retries_skips_and_stops_at_want(
    tmp_path: Path,
    monkeypatch,
):
    screen = _screen_module()
    monkeypatch.chdir(tmp_path)
    candidates = [_instance(f"candidate-{position}") for position in range(1, 9)]
    factory = _FakeScreenFactory(
        tmp_path / "executors",
        {
            "candidate-1": ["included"],
            "candidate-2": ["included"],
            "candidate-3": ["included"],
            "candidate-4": ["rule4"],
            "candidate-5": ["rule5"],
            "candidate-6": ["infra", "included"],
            "candidate-7": ["included"],
            "candidate-8": ["included"],
        },
    )
    ledger = Path("pilot/v2-screen.jsonl")

    included = await screen.screen_candidates(
        factory,
        candidates,
        ledger,
        start=2,
        exclude={"candidate-2"},
        want=3,
        concurrency=1,
    )

    assert included == ["candidate-3", "candidate-6", "candidate-7"]
    rows = [
        record.model_dump(mode="json")
        for record in screen._read_ledger(ledger)
    ]
    assert [(row["position"], row["outcome"], row["run_number"]) for row in rows] == [
        (3, "included", 1),
        (4, "excluded", 1),
        (5, "excluded", 1),
        (6, "infra_error", 1),
        (6, "included", 2),
        (7, "included", 1),
    ]
    assert rows[1]["rule"] == "4"
    assert rows[1]["failing_ids"] == [TARGET]
    assert rows[2]["rule"] == "5"
    assert rows[2]["failing_ids"] == [PROTECTED]
    assert rows[3]["rule"] is None
    assert rows[3]["official_log_path"] == "pilot/v2-screen/candidate-6/run-1/official.log"
    assert rows[3]["official_log_sha256"] == hashlib.sha256(b"").hexdigest()
    assert rows[0]["sandbox_usage"][0]["seconds"] == 1.5
    assert not Path(rows[0]["official_log_path"]).is_absolute()
    assert factory.created.get("candidate-1") is None
    assert factory.created.get("candidate-2") is None
    assert factory.created.get("candidate-8") is None
    for row in rows:
        assert (
            Path("pilot/v2-screen")
            / row["instance_id"]
            / f"run-{row['run_number']}"
        ).is_dir()


async def test_screen_resumes_after_an_infrastructure_row_without_overwriting(
    tmp_path: Path,
    monkeypatch,
):
    screen = _screen_module()
    monkeypatch.chdir(tmp_path)
    ledger = Path("pilot/resume.jsonl")
    ledger.parent.mkdir(parents=True)
    torn_fragment = b'{"position":1'
    ledger.write_bytes(torn_fragment)
    first_run = Path("pilot/resume/candidate-1/run-1")
    first_run.mkdir(parents=True)
    (first_run / "kept.txt").write_text("keep\n", encoding="utf-8")
    factory = _FakeScreenFactory(
        tmp_path / "executors",
        {"candidate-1": ["included"]},
    )

    included = await screen.screen_candidates(
        factory,
        [_instance("candidate-1")],
        ledger,
        start=1,
        exclude=set(),
        want=1,
    )
    created_after_first_resume = dict(factory.created)
    included_again = await screen.screen_candidates(
        factory,
        [_instance("candidate-1")],
        ledger,
        start=1,
        exclude=set(),
        want=1,
    )

    assert included == ["candidate-1"]
    assert included_again == included
    assert factory.created == created_after_first_resume
    rows = [
        record.model_dump(mode="json")
        for record in screen._read_ledger(ledger)
    ]
    assert [row["run_number"] for row in rows] == [1, 2]
    assert rows[0]["outcome"] == "infra_error"
    assert rows[0]["reason"] == "interrupted before the screening run was recorded"
    assert rows[0]["recovered_torn_ledger_sha256"] == hashlib.sha256(
        torn_fragment,
    ).hexdigest()
    assert rows[-1]["outcome"] == "included"
    assert (first_run / "kept.txt").read_text(encoding="utf-8") == "keep\n"
    assert Path("pilot/resume/candidate-1/run-2").is_dir()


async def test_screen_concurrency_preserves_position_selection(
    tmp_path: Path,
    monkeypatch,
):
    screen = _screen_module()
    monkeypatch.chdir(tmp_path)
    candidates = [_instance(f"candidate-{position}") for position in range(1, 4)]
    factory = _FakeScreenFactory(
        tmp_path / "executors",
        {
            "candidate-1": ["included"],
            "candidate-2": ["included"],
            "candidate-3": ["included"],
        },
        delays={"candidate-1": 0.05},
    )
    ledger = Path("pilot/concurrent.jsonl")

    included = await screen.screen_candidates(
        factory,
        candidates,
        ledger,
        start=1,
        exclude=set(),
        want=2,
        concurrency=2,
    )

    assert factory.max_active == 2
    assert included == ["candidate-1", "candidate-2"]
    assert factory.created.get("candidate-3") is None
    assert sorted(
        row["position"]
        for row in _read_ledger(ledger)
        if row["outcome"] == "included"
    ) == [1, 2]
