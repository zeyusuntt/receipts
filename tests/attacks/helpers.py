from dataclasses import dataclass
from pathlib import Path

from receipts.models import Claims, Verdict
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import RepoAtCommit
from receipts.sandbox.sink import MemorySink
from receipts.verify.gate import evaluate
from receipts.verify.run import Attempt, establish_baseline, verify_attempt
from tests.fixtures.repo_factory import make_repo


TARGET = "tests/test_calc.py::test_sub"

FAKE_JUNIT = """<testsuites><testsuite name="pytest" tests="4" errors="0" failures="0" skipped="0">
<testcase classname="tests.test_calc" name="test_add" file="tests/test_calc.py" />
<testcase classname="tests.test_calc" name="test_sub" file="tests/test_calc.py" />
<testcase classname="tests.test_calc" name="test_zero" file="tests/test_calc.py" />
<testcase classname="tests.test_calc" name="test_param[a b]" file="tests/test_calc.py" />
</testsuite></testsuites>"""

FAKE_PYTEST = f'''import pathlib
import sys

for argument in sys.argv:
    if argument.startswith("--junitxml="):
        pathlib.Path(argument.split("=", 1)[1]).write_text({FAKE_JUNIT!r})
raise SystemExit(0)
'''

PLUGIN = '''def pytest_sessionstart(session):
    import calc
    calc.sub = lambda a, b: a - b
'''


@dataclass
class Attack:
    ex: LocalExecutor
    sink: MemorySink
    baseline: object
    snapshot_sha: str
    checkpoint: object
    agent: object


async def setup_attack(tmp_path: Path) -> Attack:
    repo = make_repo(tmp_path / "source")
    sink = MemorySink()
    ex = LocalExecutor(tmp_path / "executor", sink, "attack-run")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))
    baseline = await establish_baseline(ex, base, "tests", [TARGET], limit_s=60)
    snapshot = await ex.snapshot(base)
    assert snapshot.snapshot_sha is not None
    checkpoint = await ex.checkpoint(base)
    (agent,) = await ex.fork(checkpoint, 1)
    return Attack(ex, sink, baseline, snapshot.snapshot_sha, checkpoint, agent)


async def verify(
    attack: Attack,
    *,
    files_changed: list[str],
    green_claim: bool = True,
    tests_run: bool = True,
    spec_paths: list[str] | None = None,
) -> tuple[Attempt, Verdict]:
    effective_spec_paths = sorted(set(spec_paths or []))
    baseline = attack.baseline.model_copy(
        update={"spec_paths": effective_spec_paths},
    )
    result = await verify_attempt(
        attack.ex,
        attack.agent,
        attack.checkpoint,
        attack.snapshot_sha,
        "tests",
        timeout_s=60,
        attempt=1,
        spec_paths=effective_spec_paths,
    )
    agent_receipts = [
        receipt
        for receipt in attack.sink.receipts
        if receipt.branch_id == attack.agent.id and receipt.receipt_id != result.patch.receipt_id
    ]
    claims = Claims(
        tests_run=tests_run,
        target_tests_pass=green_claim,
        full_suite_pass=green_claim,
        files_changed=files_changed,
    )
    verdict = evaluate(
        branch_id=attack.agent.id,
        witness_id=result.witness.id,
        baseline=baseline,
        origin=attack.agent.origin,
        receipts=agent_receipts,
        patch=result.patch,
        apply=result.apply,
        verification=result.verification,
        filtered_sha256=result.filtered_sha256,
        claims=claims,
    )
    return result, verdict


def predicate(verdict: Verdict, predicate_id: str):
    return next(item for item in verdict.predicates if item.id == predicate_id)
