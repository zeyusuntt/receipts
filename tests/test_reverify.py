from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import shutil
import subprocess
import uuid
from difflib import unified_diff
from pathlib import Path

import pytest

from receipts.cli import main
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import ImageSource, RepoAtCommit
from receipts.sandbox.sink import MemorySink
from receipts.swerebench import Instance
from tests.fixtures.repo_factory import CALC, TEST_CALC, _git, make_repo


TARGET = "tests/test_calc.py::test_sub"
FIXED = CALC.replace("a + b  # bug: should be a - b", "a - b")


def module():
    return importlib.import_module("receipts.reverify")


def diff(path, before, after):
    return f"diff --git a/{path} b/{path}\n" + "".join(unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}",
    ))


def instance(**updates):
    values = dict(
        instance_id="fixture__calc-1", repo="fixture/calc", base_commit="HEAD",
        image_name="docker.io/fixture/calc:test", problem_statement="Fix subtraction",
        test_patch=diff("tests/test_calc.py", TEST_CALC, TEST_CALC + "\n# spec marker\n"),
        fail_to_pass=[TARGET], pass_to_pass=["tests/test_calc.py::test_add"],
        test_cmd="python -m pytest tests",
    )
    values.update(updates)
    return Instance(**values)


def bundle(**updates):
    patch = diff("calc/__init__.py", CALC, FIXED)
    digest = hashlib.sha256(patch.encode()).hexdigest()
    values = dict(
        schema="receipts-bundle/1", instance=instance().model_dump(mode="json"),
        run=dict(run_id="fixture-run", executor_kind="local", model={"model": "fake"},
                 code_version="0.0.1", budgets={"baseline_limit_s": 600, "verification_timeout_s": 60}),
        shipped=dict(number=2, patch=patch, sha256=digest, filtered_sha256=digest,
                     agent_patch=patch, agent_patch_sha256=digest),
        claims=dict(gate_status="PASS", failed_predicate_ids=[], claim_audit="honest", official_resolved=True),
    )
    values.update(updates)
    return values


def write_bundle(tmp_path, values=None):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(values or bundle()), encoding="utf-8")
    return path


def recorded_pilot(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures/site"
    shutil.copytree(fixture, tmp_path / "recorded")
    monkeypatch.chdir(tmp_path / "recorded")
    # The static-site fixture splits these RunResult fields into sibling files.
    # Restore the complete on-disk RunResult the exporter consumes.
    run = Path("runs/synthetic__appeal-1")
    result = json.loads((run / "result.json").read_text())
    for field in ("input", "baseline", "plan", "disclosure"):
        result[field] = json.loads((run / f"{field}.json").read_text())
    (run / "result.json").write_text(json.dumps(result))
    pilot = Path("pilot")
    for other in ("twisted__towncrier-696", "pypa__twine-1066"):
        shutil.rmtree(pilot / other)
    return pilot


class ImageLocal(LocalExecutor):
    """Replace only image provisioning; run the actual executor and gate locally."""

    def __init__(self, root, repo):
        super().__init__(root, MemorySink(), "reverify-test")
        self.repo = repo
        self.prepared_source = None
        self.active = {}
        self.closed = False
        self.applied = []

    async def prepare(self, source):
        assert isinstance(source, ImageSource)
        self.prepared_source = source
        branch = await super().prepare(RepoAtCommit(url=str(self.repo), commit="HEAD", install_cmd="true"))
        self.active[branch.id] = branch
        for command in source.setup:
            result = await self.run(branch, command, timeout_s=60)
            assert result.exit_code == 0, result.stderr_tail
        return branch

    async def fork(self, checkpoint, n, prefix="b"):
        branches = await super().fork(checkpoint, n, prefix)
        self.active.update((branch.id, branch) for branch in branches)
        return branches

    async def apply_patch(self, branch, patch_text):
        self.applied.append((branch.id, patch_text))
        return await super().apply_patch(branch, patch_text)

    async def release(self, branch):
        await super().release(branch)
        self.active.pop(branch.id, None)

    async def close(self):
        for branch in list(self.active.values()):
            await self.release(branch)
        self.closed = True


@pytest.fixture
def local(tmp_path):
    repo = make_repo(tmp_path / "source")
    return ImageLocal(tmp_path / "executor", repo)


def test_export_final_attempt_and_portable_instance(tmp_path, monkeypatch):
    pilot = recorded_pilot(tmp_path, monkeypatch)
    agent_path = Path("runs/synthetic__appeal-1/attempts/2/patch.diff")
    agent_path.write_bytes(agent_path.read_bytes().replace(b"\n", b"\r\n"))
    row = instance(instance_id="synthetic__appeal-1").model_dump(mode="json")
    row["FAIL_TO_PASS"] = row.pop("fail_to_pass")
    row["PASS_TO_PASS"] = row.pop("pass_to_pass")
    row["install_config"] = {"test_cmd": row.pop("test_cmd")}
    row["patch"] = "gold patch must not be bundled"
    rows = tmp_path / "rows.jsonl"
    rows.write_text(json.dumps(row) + "\n")
    out = tmp_path / "bundles"
    assert main(["export", str(pilot), "--rows", str(rows), "--out", str(out)]) == 0
    exported = out / "synthetic__appeal-1.json"
    raw = exported.read_bytes()
    result = json.loads(raw)
    assert raw.endswith(b"\n")
    assert result["schema"] == "receipts-bundle/1"
    assert result["instance"] == instance(instance_id="synthetic__appeal-1").model_dump(mode="json")
    assert result["shipped"]["number"] == 2
    expected = Path("runs/synthetic__appeal-1/attempts/2/filtered.diff").read_bytes()
    assert result["shipped"]["patch"].encode() == expected
    assert result["shipped"]["sha256"] == hashlib.sha256(expected).hexdigest()
    expected_agent = agent_path.read_bytes()
    assert result["shipped"]["agent_patch"].encode("utf-8") == expected_agent
    assert result["shipped"]["agent_patch_sha256"] == hashlib.sha256(expected_agent).hexdigest()
    assert result["claims"]["gate_status"] == "PASS"
    assert result["claims"]["official_resolved"] is True
    assert result["run"]["model"]["temperature"] == 1.0
    assert main(["export", str(pilot), "--rows", str(rows), "--out", str(out)]) == 0
    assert exported.read_bytes() == raw


def test_export_refuses_record_digest_mismatch(tmp_path, monkeypatch, capsys):
    pilot = recorded_pilot(tmp_path, monkeypatch)
    patch = Path("runs/synthetic__appeal-1/attempts/2/filtered.diff")
    patch.write_bytes(patch.read_bytes() + b"x")
    rows = tmp_path / "rows.jsonl"
    rows.write_text(instance(instance_id="synthetic__appeal-1").model_dump_json() + "\n")
    assert main(["export", str(pilot), "--rows", str(rows), "--out", str(tmp_path / "out")]) == 1
    assert "digest" in capsys.readouterr().out.lower()
    assert not (tmp_path / "out/synthetic__appeal-1.json").exists()


def test_export_refuses_missing_agent_patch(tmp_path, monkeypatch, capsys):
    pilot = recorded_pilot(tmp_path, monkeypatch)
    Path("runs/synthetic__appeal-1/attempts/2/patch.diff").unlink()
    rows = tmp_path / "rows.jsonl"
    rows.write_text(instance(instance_id="synthetic__appeal-1").model_dump_json() + "\n")
    assert main(["export", str(pilot), "--rows", str(rows), "--out", str(tmp_path / "out")]) == 1
    assert "patch.diff" in capsys.readouterr().out
    assert not (tmp_path / "out/synthetic__appeal-1.json").exists()


async def test_reverify_agrees_with_real_gate_and_official_grade(tmp_path, local, capsys):
    path = write_bundle(tmp_path)
    assert await module().reverify(path, make_executor=lambda run_id: local) == 0
    report = capsys.readouterr().out
    assert "DISAGREES" not in report
    assert report.count("AGREES") >= 4
    assert "Every check agrees with the receipt." in report and "s)" in report
    assert local.prepared_source.image == "docker.io/fixture/calc:test"
    assert local.prepared_source.platform == "linux/amd64"
    assert local.closed and not local.active
    assert {name for name, _ in local.applied} >= {"agent1", "w1", "official1"}
    assert all(patch == bundle()["shipped"]["patch"] for _, patch in local.applied)


@pytest.mark.parametrize("field", ["sha256", "filtered_sha256"])
async def test_tampered_digest_never_builds_executor(tmp_path, capsys, field):
    values = bundle()
    if field == "sha256":
        values["shipped"]["patch"] += "x"
    else:
        values["shipped"][field] = "0" * 64
    def forbidden(run_id):
        pytest.fail("digest disagreement must not create an executor")
    assert await module().reverify(write_bundle(tmp_path, values), make_executor=forbidden) == 1
    assert "Digest" in capsys.readouterr().out


async def test_tampered_agent_patch_never_builds_executor(tmp_path, capsys):
    values = bundle()
    values["shipped"]["agent_patch"] += "x"

    def forbidden(run_id):
        pytest.fail("agent patch digest disagreement must not create an executor")

    assert await module().reverify(write_bundle(tmp_path, values), make_executor=forbidden) == 1
    report = capsys.readouterr().out
    assert "Digests" in report and "agent patch" in report and "DISAGREES" in report


@pytest.mark.parametrize("dropped_kind", ["test", "config"])
async def test_full_agent_patch_reproduces_r4_rejection(tmp_path, local, capsys, dropped_kind):
    values = bundle()
    if dropped_kind == "test":
        before = TEST_CALC + "\n# spec marker\n"
        dropped_patch = diff("tests/test_calc.py", before, before + "# agent changed this test\n")
    else:
        before = '[tool.pytest.ini_options]\npythonpath = ["."]\n'
        dropped_patch = diff("pyproject.toml", before, before + "# agent changed configuration\n")
    agent_patch = values["shipped"]["patch"] + dropped_patch
    values["shipped"].update(agent_patch=agent_patch,
                              agent_patch_sha256=hashlib.sha256(agent_patch.encode()).hexdigest())
    values["claims"].update(gate_status="REJECTED", failed_predicate_ids=["R4_patch_scope"])

    assert await module().reverify(write_bundle(tmp_path, values), make_executor=lambda _: local) == 0
    report = capsys.readouterr().out
    assert "DISAGREES" not in report
    gate_line = next(line for line in report.splitlines() if "Gate verdict" in line)
    assert "REJECTED" in gate_line and gate_line.rstrip().split("  ")[-2].strip() == "AGREES"
    failed_line = next(line for line in report.splitlines() if "Failed checks" in line)
    assert "R4_patch_scope" in failed_line and "DISAGREES" not in failed_line
    assert local.applied == [
        ("agent1", agent_patch), ("w1", values["shipped"]["patch"]),
        ("official1", values["shipped"]["patch"]),
    ]
    assert local.closed and not local.active


async def test_claimed_gate_status_disagrees(tmp_path, local, capsys):
    values = bundle()
    values["claims"]["gate_status"] = "REJECTED"
    assert await module().reverify(write_bundle(tmp_path, values), make_executor=lambda run_id: local) == 1
    assert "DISAGREES" in capsys.readouterr().out
    assert local.closed and not local.active


async def test_executor_failure_releases_even_partially_prepared_sandboxes(tmp_path, local, capsys):
    original = local.prepare
    async def failed(source):
        await original(source)
        raise RuntimeError("image provisioning failed")
    local.prepare = failed
    assert await module().reverify(write_bundle(tmp_path), make_executor=lambda run_id: local) == 2
    assert "image provisioning failed" in capsys.readouterr().out
    assert local.closed and not local.active


async def test_cancellation_releases_sandboxes(tmp_path, local):
    async def cancelled(*args, **kwargs):
        if kwargs.get("kind") == "verification":
            raise asyncio.CancelledError
        return await original(*args, **kwargs)
    original = local.run_pytest
    local.run_pytest = cancelled
    with pytest.raises(asyncio.CancelledError):
        await module().reverify(write_bundle(tmp_path), make_executor=lambda run_id: local)
    assert local.closed and not local.active
    assert "w1" in {name for name, _ in local.applied}


@pytest.mark.parametrize("bad_id", ["../escape", "/tmp/escape", "has space", "", ".", "..", "é"])
async def test_bad_instance_ids_are_refused_before_executor(tmp_path, bad_id):
    values = bundle()
    values["instance"]["instance_id"] = bad_id
    def forbidden(run_id):
        pytest.fail("invalid ID must not create an executor")
    assert await module().reverify(write_bundle(tmp_path, values), make_executor=forbidden) == 1


def test_help_describes_emulation(capsys):
    with pytest.raises(SystemExit) as exited:
        main(["reverify", "--help"])
    assert exited.value.code == 0
    assert "linux/amd64" in capsys.readouterr().out


@pytest.mark.parametrize("claim,expected", [
    ("failed_predicate_ids", ["R1_fail_to_pass"]),
    ("official_resolved", False),
    ("official_resolved", None),
])
async def test_mismatched_claims_are_disagreements(tmp_path, local, capsys, claim, expected):
    values = bundle()
    values["claims"][claim] = expected
    assert await module().reverify(write_bundle(tmp_path, values), make_executor=lambda run_id: local) == 1
    assert "DISAGREES" in capsys.readouterr().out
    assert local.closed and not local.active


async def test_rejected_empty_patch_agrees(tmp_path, local, capsys):
    values = bundle()
    values["shipped"].update(patch="", sha256=hashlib.sha256(b"").hexdigest(),
                              filtered_sha256=hashlib.sha256(b"").hexdigest(),
                              agent_patch="", agent_patch_sha256=hashlib.sha256(b"").hexdigest())
    values["claims"].update(gate_status="REJECTED", failed_predicate_ids=["R1_fail_to_pass"],
                             claim_audit="no_claim", official_resolved=False)
    assert await module().reverify(write_bundle(tmp_path, values), make_executor=lambda run_id: local) == 0
    assert "DISAGREES" not in capsys.readouterr().out


async def test_crlf_patch_is_applied_without_normalizing_bytes(tmp_path, local):
    values = bundle()
    patch = values["shipped"]["patch"].replace("\n", "\r\n")
    digest = hashlib.sha256(patch.encode()).hexdigest()
    values["shipped"].update(patch=patch, sha256=digest, filtered_sha256=digest,
                              agent_patch=patch, agent_patch_sha256=digest)
    assert await module().reverify(write_bundle(tmp_path, values), make_executor=lambda run_id: local) == 0
    assert all(text == patch for _, text in local.applied)


def test_docker_unavailable_cli_is_infrastructure(tmp_path, monkeypatch, capsys):
    import receipts.cli as cli

    async def unavailable(*_args, **_kwargs):
        return False, "Docker daemon is not running"
    monkeypatch.setattr(cli, "_docker_ready", unavailable)
    assert main(["reverify", str(write_bundle(tmp_path))]) == 2
    assert "Infrastructure failure: Docker daemon is not running" in capsys.readouterr().out


async def test_cleanup_failure_is_infrastructure(tmp_path, local, capsys):
    original = local.close
    async def failed_close():
        await original()
        raise RuntimeError("cleanup failed")
    local.close = failed_close
    assert await module().reverify(write_bundle(tmp_path), make_executor=lambda run_id: local) == 2
    assert "cleanup failed" in capsys.readouterr().out
    assert not local.active


async def test_tokenfactory_client_cleanup_failure_is_infrastructure(tmp_path, local, monkeypatch, capsys):
    import receipts.cli as cli
    import receipts.sandbox.busybox as busybox
    from receipts.sandbox.tokenfactory_api import TokenFactorySandboxApi

    class FailingCloseApi:
        async def aclose(self):
            raise RuntimeError("client cleanup failed")
    api = FailingCloseApi()
    monkeypatch.setattr(TokenFactorySandboxApi, "from_env", lambda: api)
    monkeypatch.setattr(busybox, "load_busybox", lambda: b"fixture")
    monkeypatch.setattr(cli, "tokenfactory_executor_factory", lambda *args: lambda _: local)
    assert await module().reverify(write_bundle(tmp_path), executor="tokenfactory") == 2
    assert local.closed and not local.active
    assert "client cleanup failed" in capsys.readouterr().out


async def test_missing_witness_junit_is_infrastructure(tmp_path, local, capsys):
    original = local.run_pytest
    async def missing(*args, **kwargs):
        receipt = await original(*args, **kwargs)
        if kwargs.get("kind") == "verification":
            return receipt.model_copy(update={"junit": None})
        return receipt
    local.run_pytest = missing
    assert await module().reverify(write_bundle(tmp_path), make_executor=lambda _: local) == 2
    assert local.closed and not local.active
    assert "Infrastructure failure" in capsys.readouterr().out


@pytest.mark.parametrize("fault", ["exit_127", "missing_diff"])
async def test_unusable_witness_evidence_cannot_agree_with_error_claim(tmp_path, local, fault):
    values = bundle()
    values["claims"].update(gate_status="ERROR", failed_predicate_ids=[])
    if fault == "exit_127":
        original = local.run_pytest
        async def broken(*args, **kwargs):
            receipt = await original(*args, **kwargs)
            if kwargs.get("kind") == "verification":
                return receipt.model_copy(update={"exit_code": 127})
            return receipt
        local.run_pytest = broken
    else:
        original = local.patch
        async def broken(*args, **kwargs):
            receipt = await original(*args, **kwargs)
            return receipt.model_copy(update={"diff": None})
        local.patch = broken
    assert await module().reverify(write_bundle(tmp_path, values), make_executor=lambda _: local) == 2
    assert local.closed and not local.active


async def test_filter_mismatch_stops_before_witness_and_official(tmp_path, local, capsys):
    values = bundle()
    patch = values["shipped"]["patch"] + diff("tests/test_calc.py", TEST_CALC + "\n# spec marker\n", TEST_CALC)
    digest = hashlib.sha256(patch.encode()).hexdigest()
    values["shipped"].update(patch=patch, sha256=digest, filtered_sha256=digest)
    assert await module().reverify(write_bundle(tmp_path, values), make_executor=lambda _: local) == 1
    report = capsys.readouterr().out
    filter_line = next(line for line in report.splitlines() if " Filter " in line)
    assert "DISAGREES" in filter_line and "receipt says" in filter_line
    assert not local.applied
    assert local.closed and not local.active


@pytest.mark.parametrize("operation", ["prepare", "fork"])
async def test_cancellation_finishes_provisioning_before_releasing(tmp_path, local, operation):
    ready = asyncio.Event()
    resume = asyncio.Event()
    completed = False
    original = getattr(local, operation)

    async def delayed(*args, **kwargs):
        nonlocal completed
        result = await original(*args, **kwargs)
        ready.set()
        await resume.wait()
        completed = True
        return result

    setattr(local, operation, delayed)
    task = asyncio.create_task(module().reverify(write_bundle(tmp_path), make_executor=lambda _: local))
    await asyncio.wait_for(ready.wait(), 5)
    task.cancel()
    resume.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed, "provisioning must finish before cancellation propagates"
    assert local.closed and not local.active


@pytest.mark.parametrize("bad_id", ["../escape", "has space", ".", "..", "é"])
def test_export_bad_instance_ids(tmp_path, monkeypatch, bad_id):
    pilot = recorded_pilot(tmp_path, monkeypatch)
    path = pilot / "synthetic__appeal-1/record.json"
    record = json.loads(path.read_text())
    record["instance_id"] = bad_id
    path.write_text(json.dumps(record))
    rows = tmp_path / "rows.jsonl"
    rows.write_text(instance().model_dump_json() + "\n")
    assert main(["export", str(pilot), "--rows", str(rows), "--out", str(tmp_path / "out")]) == 1


def test_export_refuses_run_directory_outside_cwd(tmp_path, monkeypatch, capsys):
    pilot = recorded_pilot(tmp_path, monkeypatch)
    path = pilot / "synthetic__appeal-1/record.json"
    record = json.loads(path.read_text())
    record["run_dir"] = "../elsewhere"
    path.write_text(json.dumps(record))
    rows = tmp_path / "rows.jsonl"
    rows.write_text(instance(instance_id="synthetic__appeal-1").model_dump_json() + "\n")
    assert main(["export", str(pilot), "--rows", str(rows), "--out", str(tmp_path / "out")]) == 1
    assert "run_dir must stay inside cwd" in capsys.readouterr().out


def _docker_available():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.docker
@pytest.mark.skipif(not _docker_available(), reason="Docker daemon is not reachable")
async def test_docker_reverify_on_fresh_image(tmp_path, monkeypatch):
    from receipts.sandbox.docker import DockerExecutor

    # SWE-rebench images are linux/amd64 and to_task pins that platform. The fixture
    # image here is built locally for the host's platform, so the pin is dropped.
    original_to_task = module().to_task

    def host_platform_task(instance):
        task = original_to_task(instance)
        return task.model_copy(update={"source": task.source.model_copy(update={"platform": None})})

    monkeypatch.setattr(module(), "to_task", host_platform_task)

    def docker(*args, check=True):
        return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=120)

    # Use the same prebuilt local test image as test_docker_executor; no pull.
    image = "receipts-test-base:py312"
    if docker("image", "inspect", image, check=False).returncode:
        pytest.skip(f"local test image {image} is unavailable")
    repo = make_repo(tmp_path / "source")
    name = f"reverify-fixture-{uuid.uuid4().hex[:12]}"
    fixture_image = None
    run_id = f"reverify-docker-{uuid.uuid4().hex[:12]}"
    try:
        docker("create", "--name", name, image)
        docker("start", name)
        docker("exec", name, "mkdir", "-p", "/calc")
        docker("cp", f"{repo}/.", f"{name}:/calc")
        docker("exec", "-u", "0", name, "chown", "-R", "0:0", "/calc")
        fixture_image = docker("commit", name).stdout.strip()
        values = bundle()
        values["instance"]["image_name"] = fixture_image
        executor = DockerExecutor(tmp_path / "executor", MemorySink(), run_id)
        assert await module().reverify(write_bundle(tmp_path, values), make_executor=lambda _: executor) == 0
        assert not docker("ps", "-aq", "--filter", f"name={run_id}").stdout.strip()
    finally:
        docker("rm", "-f", name, check=False)
        if fixture_image is not None:
            docker("image", "rm", fixture_image, check=False)
