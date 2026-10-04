from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import receipts.verify.run as verify_run
from receipts.models import Branch, Checkpoint, JunitSummary, Receipt
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import RepoAtCommit
from receipts.sandbox.sink import MemorySink
from receipts.verify.run import (
    BaselineTooSlow,
    TargetNotFailing,
    establish_baseline,
    rerun_one,
    verify_attempt,
)
from tests.fixtures.repo_factory import _git, make_repo

T = "tests/test_calc.py::test_sub"
DATASET_SIM910_KEY = "tests/test_900_rules.py::test_sim910[d.get(key,"
DATASET_SIM910_QUOTED_KEY = "tests/test_900_rules.py::test_sim910[d.get('key',"
FULL_SIM910_KEY = (
    "tests/test_900_rules.py::test_sim910[d.get(key, None)-"
    "SIM910 Use 'd.get(key)' instead of 'd.get(key, None)']"
)
FULL_SIM910_QUOTED_KEY = (
    "tests/test_900_rules.py::test_sim910[d.get('key', None)-"
    'SIM910 Use \'d.get("key")\' instead of \'d.get(\'key\', None)\']'
)


@pytest.mark.parametrize(
    ("targets", "collected", "expected"),
    [
        pytest.param(
            [FULL_SIM910_KEY],
            [FULL_SIM910_KEY],
            {FULL_SIM910_KEY: [FULL_SIM910_KEY]},
            id="exact-match",
        ),
        pytest.param(
            [DATASET_SIM910_KEY],
            [FULL_SIM910_KEY],
            {DATASET_SIM910_KEY: [FULL_SIM910_KEY]},
            id="one-truncated-match",
        ),
        pytest.param(
            [DATASET_SIM910_KEY],
            [
                FULL_SIM910_KEY.replace("None", "missing"),
                FULL_SIM910_KEY,
            ],
            {
                DATASET_SIM910_KEY: sorted(
                    [
                        FULL_SIM910_KEY.replace("None", "missing"),
                        FULL_SIM910_KEY,
                    ],
                ),
            },
            id="many-truncated-matches-are-sorted",
        ),
        pytest.param(
            [DATASET_SIM910_KEY],
            ["tests/test_other.py::test_other"],
            {DATASET_SIM910_KEY: [DATASET_SIM910_KEY]},
            id="no-match-is-unchanged",
        ),
        pytest.param(
            [FULL_SIM910_KEY, DATASET_SIM910_QUOTED_KEY, "tests/test_new.py::test_new"],
            [FULL_SIM910_QUOTED_KEY, FULL_SIM910_KEY],
            {
                FULL_SIM910_KEY: [FULL_SIM910_KEY],
                DATASET_SIM910_QUOTED_KEY: [FULL_SIM910_QUOTED_KEY],
                "tests/test_new.py::test_new": ["tests/test_new.py::test_new"],
            },
            id="mixed",
        ),
    ],
)
def test_map_target_ids(targets, collected, expected):
    assert verify_run.map_target_ids(targets, collected) == expected


async def _setup(tmp_path, flaky=False):
    repo = make_repo(tmp_path / "src", flaky=flaky)
    sink = MemorySink()
    ex = LocalExecutor(root=tmp_path / "work", sink=sink, run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))
    return ex, base, sink


def _add_sim910_tests(repo, cases):
    rendered = ",\n".join(
        f"        pytest.param({passes!r}, id={node_id!r})"
        for node_id, passes in cases
    )
    (repo / "tests" / "test_900_rules.py").write_text(
        "import pytest\n\n\n"
        "@pytest.mark.parametrize(\"passes\", [\n"
        f"{rendered}\n"
        "])\n"
        "def test_sim910(passes):\n"
        "    assert passes\n",
        encoding="utf-8",
    )
    _git(repo, "add", "tests/test_900_rules.py")
    _git(repo, "commit", "-q", "-m", "add SIM910 specification tests")


async def _sim910_executor(tmp_path, cases):
    repo = make_repo(tmp_path / "src")
    _add_sim910_tests(repo, cases)
    sink = MemorySink()
    ex = LocalExecutor(root=tmp_path / "work", sink=sink, run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))
    return ex, base


async def test_baseline_runs_twice_and_marks_unstable(tmp_path):
    ex, base, sink = await _setup(tmp_path, flaky=True)
    b = await establish_baseline(
        ex,
        base,
        "tests",
        [T],
        limit_s=600,
        spec_paths=["z/fixture.yaml", "test.py", "z/fixture.yaml"],
    )
    assert len(b.runs) == 2 and len(b.run_receipt_ids) == 2
    assert b.unstable == ["tests/test_flaky.py::test_flaky"]
    assert set(b.protected) == {"tests/test_calc.py::test_add", "tests/test_calc.py::test_zero", "tests/test_calc.py::test_param[a b]"}
    assert set(b.collected_ids) == set(b.protected) | {T, "tests/test_flaky.py::test_flaky"}
    assert b.skipped_ids == [] and b.target == [T]
    assert b.spec_paths == ["test.py", "z/fixture.yaml"]
    assert [r.kind for r in sink.receipts].count("command") == 3  # install + two baseline runs


async def test_baseline_rejects_passing_target(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    with pytest.raises(TargetNotFailing) as info:
        await establish_baseline(ex, base, "tests", ["tests/test_calc.py::test_add"], limit_s=600)
    assert info.value.node_ids == ["tests/test_calc.py::test_add"]


async def test_baseline_rejects_unknown_target(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    with pytest.raises(TargetNotFailing):
        await establish_baseline(ex, base, "tests", ["tests/test_calc.py::test_missing"], limit_s=600)


async def test_baseline_rejects_flaky_target(tmp_path):
    ex, base, _ = await _setup(tmp_path, flaky=True)
    with pytest.raises(TargetNotFailing) as info:
        await establish_baseline(ex, base, "tests", ["tests/test_flaky.py::test_flaky"], limit_s=600)
    assert info.value.node_ids == ["tests/test_flaky.py::test_flaky"]


async def test_baseline_maps_truncated_targets_and_validates_every_full_id(tmp_path):
    ex, base = await _sim910_executor(
        tmp_path,
        [
            (FULL_SIM910_KEY.split("[", 1)[1][:-1], False),
            (FULL_SIM910_QUOTED_KEY.split("[", 1)[1][:-1], False),
        ],
    )

    baseline = await establish_baseline(
        ex,
        base,
        "tests",
        [DATASET_SIM910_KEY, FULL_SIM910_KEY, DATASET_SIM910_QUOTED_KEY],
        limit_s=600,
    )

    assert baseline.target_map == {
        DATASET_SIM910_KEY: [FULL_SIM910_KEY],
        FULL_SIM910_KEY: [FULL_SIM910_KEY],
        DATASET_SIM910_QUOTED_KEY: [FULL_SIM910_QUOTED_KEY],
    }
    assert baseline.target == [FULL_SIM910_KEY, FULL_SIM910_QUOTED_KEY]


async def test_baseline_maps_against_ids_collected_in_either_run():
    class BaselineExecutor:
        def __init__(self):
            self.results = [
                SimpleNamespace(
                    timed_out=False,
                    duration_s=0.1,
                    exit_code=1,
                    receipt_id="baseline-1",
                    junit=JunitSummary(
                        passed=[],
                        failed=[],
                        errors=[],
                        skipped=[],
                        collection_errors=["tests/test_900_rules.py"],
                    ),
                ),
                SimpleNamespace(
                    timed_out=False,
                    duration_s=0.1,
                    exit_code=1,
                    receipt_id="baseline-2",
                    junit=JunitSummary(
                        passed=[],
                        failed=[FULL_SIM910_KEY],
                        errors=[],
                        skipped=[],
                    ),
                ),
            ]

        async def run_pytest(self, *args, **kwargs):
            return self.results.pop(0)

    baseline = await establish_baseline(
        BaselineExecutor(),
        object(),
        "tests",
        [DATASET_SIM910_KEY],
        limit_s=600,
    )

    assert baseline.target_map == {DATASET_SIM910_KEY: [FULL_SIM910_KEY]}
    assert baseline.target == [FULL_SIM910_KEY]


async def test_baseline_keeps_target_failure_text_from_first_run():
    class BaselineExecutor:
        def __init__(self):
            self.results = [
                SimpleNamespace(
                    timed_out=False,
                    duration_s=0.1,
                    exit_code=1,
                    receipt_id=f"baseline-{index}",
                    junit=JunitSummary(
                        passed=[],
                        failed=[T],
                        errors=[],
                        skipped=[],
                        failure_text={T: text},
                    ),
                )
                for index, text in enumerate(
                    ["first run assertion", "second run assertion"],
                    start=1,
                )
            ]

        async def run_pytest(self, *args, **kwargs):
            return self.results.pop(0)

    baseline = await establish_baseline(
        BaselineExecutor(),
        object(),
        "tests",
        [T],
        limit_s=600,
    )

    assert baseline.target_failure_text == {T: "first run assertion"}


async def test_baseline_uses_first_run_collection_error_text_for_target_file():
    target = "tests/test_new.py::test_new"

    class BaselineExecutor:
        def __init__(self):
            self.results = [
                SimpleNamespace(
                    timed_out=False,
                    duration_s=0.1,
                    exit_code=1,
                    receipt_id="baseline-1",
                    junit=JunitSummary(
                        passed=[],
                        failed=[],
                        errors=[],
                        skipped=[],
                        collection_errors=["tests/test_new.py"],
                        failure_text={"tests/test_new.py": "ModuleNotFoundError: feature"},
                    ),
                ),
                SimpleNamespace(
                    timed_out=False,
                    duration_s=0.1,
                    exit_code=1,
                    receipt_id="baseline-2",
                    junit=JunitSummary(
                        passed=[],
                        failed=[target],
                        errors=[],
                        skipped=[],
                    ),
                ),
            ]

        async def run_pytest(self, *args, **kwargs):
            return self.results.pop(0)

    baseline = await establish_baseline(
        BaselineExecutor(),
        object(),
        "tests",
        [target],
        limit_s=600,
    )

    assert baseline.target_failure_text == {
        target: "ModuleNotFoundError: feature",
    }


async def test_baseline_marks_unrecorded_target_failure_text():
    class BaselineExecutor:
        def __init__(self):
            self.results = [
                SimpleNamespace(
                    timed_out=False,
                    duration_s=0.1,
                    exit_code=1,
                    receipt_id=f"baseline-{index}",
                    junit=JunitSummary(
                        passed=[],
                        failed=[T],
                        errors=[],
                        skipped=[],
                    ),
                )
                for index in (1, 2)
            ]

        async def run_pytest(self, *args, **kwargs):
            return self.results.pop(0)

    baseline = await establish_baseline(
        BaselineExecutor(),
        object(),
        "tests",
        [T],
        limit_s=600,
    )

    assert baseline.target_failure_text == {T: "(failure text not recorded)"}


async def test_baseline_marks_empty_target_failure_text_as_unrecorded():
    class BaselineExecutor:
        def __init__(self):
            self.results = [
                SimpleNamespace(
                    timed_out=False,
                    duration_s=0.1,
                    exit_code=1,
                    receipt_id=f"baseline-{index}",
                    junit=JunitSummary(
                        passed=[],
                        failed=[T],
                        errors=[],
                        skipped=[],
                        failure_text={T: ""},
                    ),
                )
                for index in (1, 2)
            ]

        async def run_pytest(self, *args, **kwargs):
            return self.results.pop(0)

    baseline = await establish_baseline(
        BaselineExecutor(),
        object(),
        "tests",
        [T],
        limit_s=600,
    )

    assert baseline.target_failure_text == {T: "(failure text not recorded)"}


async def test_baseline_rejects_many_match_when_one_full_id_passes(tmp_path):
    other_full = FULL_SIM910_KEY.replace("None", "missing")
    ex, base = await _sim910_executor(
        tmp_path,
        [
            (FULL_SIM910_KEY.split("[", 1)[1][:-1], False),
            (other_full.split("[", 1)[1][:-1], True),
        ],
    )

    with pytest.raises(TargetNotFailing) as info:
        await establish_baseline(
            ex,
            base,
            "tests",
            [DATASET_SIM910_KEY],
            limit_s=600,
        )

    assert info.value.node_ids == [DATASET_SIM910_KEY]
    assert DATASET_SIM910_KEY in str(info.value)
    assert FULL_SIM910_KEY in str(info.value)
    assert other_full in str(info.value)


async def test_baseline_too_slow(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    with pytest.raises(BaselineTooSlow):
        await establish_baseline(ex, base, "tests", [T], limit_s=0)


@pytest.mark.parametrize(
    ("timed_out", "duration_s", "message"),
    [
        (True, 0.0, "baseline suite timed out after 600s"),
        (False, 650.0, "baseline suite took 650s, over the 600s limit"),
    ],
)
async def test_baseline_too_slow_message_distinguishes_timeout(
    timed_out, duration_s, message,
):
    async def run_pytest(branch, args, *, timeout_s):
        assert timeout_s == 600
        return SimpleNamespace(timed_out=timed_out, duration_s=duration_s)

    with pytest.raises(BaselineTooSlow) as info:
        await establish_baseline(
            SimpleNamespace(run_pytest=run_pytest),
            Branch(id="base", run_id="run-1", head="c0", origin="c0"),
            "tests", [T], limit_s=600,
        )

    assert str(info.value) == message
    assert info.value.seconds == duration_s


@pytest.mark.parametrize(
    ("timed_out", "message"),
    [
        (True, "baseline suite timed out after 300s"),
        (False, "baseline suite took 315s, over the 300s limit"),
    ],
)
async def test_baseline_guard_message_uses_its_own_limit(timed_out, message):
    from receipts.pilot.runner import _BaselineGuard

    async def run_pytest(*args, **kwargs):
        return SimpleNamespace(timed_out=timed_out, duration_s=315.0)

    with pytest.raises(BaselineTooSlow) as info:
        await _BaselineGuard(run_pytest, limit_s=300)()

    assert str(info.value) == message


async def test_baseline_guard_timeout_message_uses_command_deadline():
    from receipts.pilot.runner import _BaselineGuard

    async def run_pytest(*args, **kwargs):
        return SimpleNamespace(timed_out=True, duration_s=600.0)

    with pytest.raises(BaselineTooSlow) as info:
        await _BaselineGuard(run_pytest, limit_s=300)(timeout_s=600)

    assert str(info.value) == "baseline suite timed out after 600s"


async def test_honest_source_fix_verifies_green_on_witness(tmp_path):
    ex, base, sink = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    fixed = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    await ex.write_file(agent, "calc/__init__.py", fixed)
    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)
    assert result.patch.kind == "diff" and result.patch.branch_id == "b1"
    assert result.filtered_patch and result.dropped == []
    assert result.witness.id == "w1" and result.apply.branch_id == "w1" and result.apply.exit_code == 0
    assert result.apply.patch_sha256 == result.filtered_sha256
    assert result.verification.kind == "verification" and result.verification.branch_id == "w1"
    assert result.verification.junit.failed == [] and result.verification.junit.collected == 4
    assert await ex.read_file(result.witness, "calc/__init__.py", 10_000) == fixed
    second = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=2)
    assert second.witness.id == "w2" and second.verification.junit.failed == []


async def test_conftest_hijack_is_dropped_and_witness_still_fails(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    hijack = '''import pytest


@pytest.fixture(autouse=True)
def force_target_green(monkeypatch):
    import tests.test_calc as test_calc
    monkeypatch.setattr(test_calc, "sub", lambda a, b: a - b)
'''
    await ex.write_file(agent, "tests/conftest.py", hijack)
    own = await ex.run_pytest(agent, "tests", timeout_s=60)
    assert own.exit_code == 0 and own.junit.failed == [] and own.junit.collected == 4
    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)
    assert result.dropped == ["tests/conftest.py"]
    assert result.patch.dropped_paths == ["tests/conftest.py"] and result.filtered_patch == ""
    assert result.verification.junit.failed == [T]


async def test_verify_attempt_drops_a_readonly_spec_path(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    fixed = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    await ex.write_file(agent, "calc/__init__.py", fixed)

    result = await verify_attempt(
        ex,
        agent,
        c0,
        snapshot.snapshot_sha,
        "tests",
        timeout_s=60,
        attempt=1,
        spec_paths=["calc/__init__.py"],
    )

    assert result.filtered_patch == ""
    assert result.dropped == ["calc/__init__.py"]
    assert result.verification.junit.failed == [T]


async def test_gitignored_agent_edit_never_reaches_witness(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    await ex.write_file(agent, "report.xml", "agent-only ignored content\n")
    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)
    assert result.patch.diff.files == [] and result.filtered_patch == "" and result.dropped == []
    assert not (ex.workdir(result.witness) / "report.xml").exists()
    assert result.verification.junit.failed == [T]


async def test_checkpoint_tampering_returns_failed_witness_apply(tmp_path):
    ex, base, sink = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    escaped = await ex.run(
        agent,
        "python -c \"from pathlib import Path; p=next(Path('..').glob('ckpt-*/tests/test_calc.py')); p.write_text('tampered\\n')\"",
        timeout_s=30,
    )
    assert escaped.exit_code == 0

    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)

    assert result.witness.id == "w1"
    assert result.apply.branch_id == "w1" and result.apply.kind == "apply"
    assert result.apply.exit_code == 1
    assert result.apply.stderr_tail == f"checkpoint {c0.id} was modified after prepare"
    assert result.verification is None
    assert sink.receipts[-1].model_dump() == result.apply.model_dump()


async def test_rerun_one_targets_a_single_node_with_brackets_and_spaces(tmp_path):
    ex, base, _ = await _setup(tmp_path)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)
    r = await rerun_one(ex, result.witness, "tests/test_calc.py::test_param[a b]", timeout_s=60)
    assert r.kind == "verification"
    assert r.branch_id == result.witness.id and r.image_before == result.verification.image_after
    assert r.junit.collected == 1 and r.junit.passed == ["tests/test_calc.py::test_param[a b]"]


NEW_SPEC = "tests/test_new_feature.py::test_new_feature"


async def test_baseline_accepts_a_spec_test_whose_module_does_not_exist_yet(tmp_path):
    """A new-feature task: the failing test imports a module the fix will create, so
    collecting its file fails at baseline. That is a failing target, not a broken suite."""
    repo = make_repo(tmp_path / "src")
    (repo / "tests" / "test_new_feature.py").write_text(
        "from calc.feature import double\n\n\ndef test_new_feature():\n    assert double(2) == 4\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add spec test for a module that does not exist yet")
    ex = LocalExecutor(root=tmp_path / "work", sink=MemorySink(), run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd="true"))

    b = await establish_baseline(ex, base, "tests", [NEW_SPEC], limit_s=600)

    assert b.target == [NEW_SPEC]
    assert b.target_map == {NEW_SPEC: [NEW_SPEC]}
    assert NEW_SPEC not in b.collected_ids
    assert "tests/test_calc.py::test_add" in b.protected
    assert all(run.collection_errors == ["tests/test_new_feature.py"] for run in b.runs)


async def test_patch_applies_to_a_witness_whose_files_have_crlf_line_endings(tmp_path):
    """Some SWE-rebench repositories keep CRLF files while git normalizes line endings on
    commit, so the extracted patch has LF lines. The witness must still take the patch, as
    the upstream grader does with its whitespace-tolerant apply flags."""
    repo = make_repo(tmp_path / "src")
    to_crlf = (
        "git config core.autocrlf input && python -c \"import pathlib; "
        "p = pathlib.Path('calc/__init__.py'); "
        "p.write_bytes(p.read_bytes().replace(b'\\\\n', b'\\\\r\\\\n'))\""
    )
    ex = LocalExecutor(root=tmp_path / "work", sink=MemorySink(), run_id="run-1")
    base = await ex.prepare(RepoAtCommit(url=str(repo), commit="HEAD", install_cmd=to_crlf))
    assert "\r\n" in await ex.read_file(base, "calc/__init__.py", 10_000)
    snapshot = await ex.snapshot(base)
    c0 = await ex.checkpoint(base)
    (agent,) = await ex.fork(c0, 1)
    original = await ex.read_file(agent, "calc/__init__.py", 10_000)
    await ex.write_file(agent, "calc/__init__.py", original.replace("return a + b  # bug: should be a - b", "return a - b"))

    result = await verify_attempt(ex, agent, c0, snapshot.snapshot_sha, "tests", timeout_s=60, attempt=1)

    assert result.apply.exit_code == 0, result.apply.stdout_tail + result.apply.stderr_tail
    assert "tests/test_calc.py::test_sub" in result.verification.junit.passed


class _ConfirmationExecutor:
    def __init__(self, *, pytest_raises: bool = False) -> None:
        self.pytest_raises = pytest_raises
        self.fork_calls = []
        self.applied = []
        self.released = []

    async def fork(self, checkpoint, n, prefix="b"):
        self.fork_calls.append((checkpoint, n, prefix))
        return [
            Branch(
                id="c1",
                run_id="run-1",
                head=checkpoint.id,
                origin=checkpoint.id,
            ),
        ]

    async def apply_patch(self, branch, patch_text):
        self.applied.append((branch.id, patch_text))
        before = branch.head
        branch.head = "c1-applied"
        return Receipt(
            receipt_id="c1-1",
            seq=1,
            branch_id=branch.id,
            kind="apply",
            exit_code=0,
            patch_sha256="patch-digest",
            image_before=before,
            image_after=branch.head,
            started_at=datetime.now(timezone.utc),
            duration_s=0.1,
        )

    async def run_pytest(self, branch, args, timeout_s, kind="command"):
        if self.pytest_raises:
            raise RuntimeError("pytest transport failed")
        before = branch.head
        branch.head = "c1-verified"
        return Receipt(
            receipt_id="c1-2",
            seq=2,
            branch_id=branch.id,
            kind=kind,
            cmd=f"pytest {args}",
            exit_code=4,
            image_before=before,
            image_after=branch.head,
            started_at=datetime.now(timezone.utc),
            duration_s=0.1,
        )

    async def release(self, branch):
        self.released.append(branch.id)


async def test_confirm_load_failure_replays_same_patch_on_a_c_branch():
    executor = _ConfirmationExecutor()
    checkpoint = Checkpoint(id="ckpt-1")

    result = await verify_run.confirm_load_failure(
        executor,
        checkpoint,
        "same filtered patch",
        "tests",
        timeout_s=60,
        attempt=1,
    )

    assert executor.fork_calls == [(checkpoint, 1, "c")]
    assert executor.applied == [("c1", "same filtered patch")]
    assert result.branch.id == "c1"
    assert result.apply.receipt_id == "c1-1"
    assert result.verification.receipt_id == "c1-2"
    assert executor.released == ["c1"]


async def test_confirm_load_failure_releases_branch_when_pytest_raises():
    executor = _ConfirmationExecutor(pytest_raises=True)

    with pytest.raises(RuntimeError, match="pytest transport failed"):
        await verify_run.confirm_load_failure(
            executor,
            Checkpoint(id="ckpt-1"),
            "same filtered patch",
            "tests",
            timeout_s=60,
            attempt=1,
        )

    assert executor.released == ["c1"]
