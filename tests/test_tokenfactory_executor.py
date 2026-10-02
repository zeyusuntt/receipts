import hashlib
import io
import importlib
import json
import os
import shutil
import subprocess
import tarfile
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from receipts.models import Branch
from receipts.sandbox.protocol import GIT_APPLY_FLAGS, PYTEST_FLAGS, ImageSource, RepoAtCommit
from receipts.sandbox.sink import MemorySink
from receipts.sandbox.staging import mirror_worktree


BASE_IMAGE = "11111111-1111-1111-1111-111111111111"
BUSYBOX = b"trusted static busybox"
ARCHIVE_ALL = "/__fixture_archive_all__.tar"
ARCHIVE_NO_GIT = "/__fixture_archive_no_git__.tar"


def _module():
    try:
        return importlib.import_module("receipts.sandbox.tokenfactory")
    except ModuleNotFoundError:
        pytest.fail("the Token Factory executor module is not implemented")


def _api_module():
    return importlib.import_module("receipts.sandbox.tokenfactory_api")


def _fake(*, handlers=None, tree=None, tags=None):
    api_module = _api_module()
    return api_module.FakeTokenFactorySandboxApi(
        images={BASE_IMAGE: tree or {"/repo/original.txt": b"original\n"}},
        tags=tags if tags is not None else {"swerebenchv2/example:1": BASE_IMAGE},
        handlers=handlers or {},
    )


def _executor(tmp_path: Path, module, api=None, **kwargs):
    sink = MemorySink()
    executor = module.TokenFactoryExecutor(
        tmp_path / "executor",
        sink,
        "run-1",
        api or _fake(),
        busybox=BUSYBOX,
        **kwargs,
    )
    return executor, executor.api, sink


def _copy_handler(incoming: str, target: str):
    def copy_file(tree: dict[str, bytes]):
        assert tree[incoming]
        tree[target] = tree[incoming]
        return 0, "", "", tree

    return copy_file


def _tar_directory(root: Path, *, include_git: bool) -> bytes:
    stream = io.BytesIO()

    def include(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(member.name).parts
        relative = parts[1:] if parts[:1] == (".",) else parts
        if not include_git and relative[:1] == (".git",):
            return None
        return member

    with tarfile.open(fileobj=stream, mode="w", dereference=False) as archive:
        archive.add(root, arcname=".", recursive=True, filter=include)
    return stream.getvalue()


def _fixture_tree(root: Path) -> dict[str, bytes]:
    return {
        ARCHIVE_ALL: _tar_directory(root, include_git=True),
        ARCHIVE_NO_GIT: _tar_directory(root, include_git=False),
    }


def _archive_fake(root: Path, *, handlers=None):
    api_module = _api_module()

    class ArchiveFake(api_module.FakeTokenFactorySandboxApi):
        async def run(self, **kwargs):
            command = kwargs["command"]
            if command.startswith("/opt/receipts-bin/busybox tar "):
                words = command.split()
                target = words[words.index("-cf") + 1]
                archive_key = (
                    ARCHIVE_NO_GIT if "--exclude=./.git" in words else ARCHIVE_ALL
                )

                def archive(tree):
                    tree[target] = tree[archive_key]
                    return 0, "", "", tree

                self.handlers[command] = archive
            return await super().run(**kwargs)

    return ArchiveFake(
        images={BASE_IMAGE: _fixture_tree(root)},
        tags={"swerebenchv2/example:1": BASE_IMAGE},
        handlers=handlers or {},
    )


def _init_repo(root: Path) -> str:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.com"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _junit_xml() -> bytes:
    return b"""\
<?xml version="1.0" encoding="utf-8"?>
<testsuite tests="1" failures="0" errors="0" skipped="0">
  <properties>
    <property name="receipts_rootdir" value="/repo" />
    <property name="receipts_invocation_dir" value="/repo" />
  </properties>
  <testcase classname="tests.test_sample" name="test_ok" file="tests/test_sample.py" />
</testsuite>
"""


def _tar_with_members(members: list[tuple[tarfile.TarInfo, bytes]]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for member, content in members:
            if member.isreg():
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            else:
                archive.addfile(member)
    return stream.getvalue()


def _tar_info(name: str, member_type: bytes, *, linkname: str = "") -> tarfile.TarInfo:
    member = tarfile.TarInfo(name)
    member.type = member_type
    member.linkname = linkname
    return member


@pytest.mark.parametrize(
    ("image", "expected_tag"),
    [
        ("swerebenchv2/example:1", "swerebenchv2/example:1"),
        ("docker.io/swerebenchv2/example:1", "swerebenchv2/example:1"),
    ],
)
async def test_prepare_resolves_catalogue_tag_and_strips_docker_hub_prefix(
    tmp_path,
    image,
    expected_tag,
):
    module = _module()
    executor, api, _ = _executor(tmp_path, module)

    base = await executor.prepare(ImageSource(image=image, workdir="/repo"))

    assert base == Branch(
        id="base",
        run_id="run-1",
        head=BASE_IMAGE,
        origin=BASE_IMAGE,
    )
    assert [call for call in api.calls if call["method"] == "image_by_tag"] == [
        {"method": "image_by_tag", "tag": expected_tag},
    ]


async def test_prepare_rejects_missing_image_wrong_source_and_second_call(tmp_path):
    module = _module()
    missing, _, _ = _executor(tmp_path / "missing", module, _fake(tags={}))
    with pytest.raises(
        RuntimeError,
        match=(
            "image not in the Token Factory Sandboxes catalogue: "
            "swerebenchv2/missing:1"
        ),
    ):
        await missing.prepare(
            ImageSource(image="docker.io/swerebenchv2/missing:1", workdir="/repo"),
        )

    executor, _, _ = _executor(tmp_path / "once", module)
    with pytest.raises(TypeError, match="ImageSource"):
        await executor.prepare(
            RepoAtCommit(url=".", commit="HEAD", install_cmd="true"),
        )
    await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )
    with pytest.raises(RuntimeError, match="only be called once"):
        await executor.prepare(
            ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
        )


@pytest.mark.parametrize(
    "workdir",
    ["repo", "/", "//repo", "/repo/../repo", "/tmp", "/tmp/repo"],
)
async def test_prepare_validates_workdir_like_daytona(tmp_path, workdir):
    module = _module()
    executor, _, _ = _executor(tmp_path, module)

    with pytest.raises(ValueError):
        await executor.prepare(
            ImageSource(image="swerebenchv2/example:1", workdir=workdir),
        )


async def test_prepare_runs_setup_commands_and_moves_the_base_head(tmp_path):
    module = _module()

    def setup(tree):
        tree["/repo/setup.txt"] = b"ready\n"
        return 0, "setup complete\n", "", tree

    api = _fake(handlers={"prepare fixture": setup})
    executor, _, sink = _executor(tmp_path, module, api)

    base = await executor.prepare(
        ImageSource(
            image="swerebenchv2/example:1",
            workdir="/repo",
            setup=["prepare fixture"],
        ),
    )

    assert len(sink.receipts) == 1
    assert sink.receipts[0].cmd == "prepare fixture"
    assert sink.receipts[0].image_before == BASE_IMAGE
    assert sink.receipts[0].image_after == base.head
    assert base.head != BASE_IMAGE
    assert await executor.read_file(base, "setup.txt", 100) == "ready\n"


async def test_every_run_injects_trusted_files_and_chains_immutable_images(tmp_path):
    module = _module()
    seen: list[dict[str, bytes]] = []

    def first(tree):
        seen.append(deepcopy(tree))
        tree["/repo/first.txt"] = b"first\n"
        return 3, "first stdout\n", "first stderr\n", tree

    def second(tree):
        seen.append(deepcopy(tree))
        assert tree["/repo/first.txt"] == b"first\n"
        return 0, "second stdout\n", "", tree

    api = _fake(handlers={"first command": first, "second command": second})
    executor, _, sink = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )

    first_receipt = await executor.run(base, "first command", timeout_s=17)
    second_receipt = await executor.run(base, "second command", timeout_s=9999)

    calls = [call for call in api.calls if call["method"] == "run"]
    assert len([call for call in api.calls if call["method"] == "upload"]) == 2
    assert calls[0]["image"] == BASE_IMAGE
    assert calls[1]["image"] == first_receipt.image_after
    assert all(call["shell"] is True for call in calls)
    assert all(call["cwd"] == "/repo" for call in calls)
    assert all(call["disposable"] is False for call in calls)
    assert calls[0]["timeout"] == 17
    assert calls[1]["timeout"] == 3600
    assert all(call["truncate_output_at"] == 10 * 1024 * 1024 - 1 for call in calls)
    for call in calls:
        assert set(call["files"]) == {
            "/opt/receipts-bin/busybox",
            "/opt/receipts/receipts_pytest.py",
        }
        assert call["files"]["/opt/receipts-bin/busybox"]["mode"] == "0755"
        assert call["files"]["/opt/receipts/receipts_pytest.py"]["mode"] == "0644"
    assert all(tree["/opt/receipts-bin/busybox"] == BUSYBOX for tree in seen)
    assert all(b"import pytest" in tree["/opt/receipts/receipts_pytest.py"] for tree in seen)
    assert first_receipt.seq == 1 and first_receipt.receipt_id == "base-1"
    assert first_receipt.image_before == BASE_IMAGE
    assert first_receipt.image_after == second_receipt.image_before
    assert second_receipt.image_after == base.head
    assert sink.receipts == [first_receipt, second_receipt]


async def test_run_without_output_image_keeps_head_and_platform_failure_raises(tmp_path):
    module = _module()
    api_module = _api_module()

    class NoImageApi(api_module.FakeTokenFactorySandboxApi):
        async def run(self, **kwargs):
            result = await super().run(**kwargs)
            return replace(result, image_uuid=None)

    class FailedApi(api_module.FakeTokenFactorySandboxApi):
        async def run(self, **kwargs):
            result = await super().run(**kwargs)
            return replace(
                result,
                exit_code=None,
                image_uuid=None,
                status="FAILED",
                error="platform capacity unavailable",
                has_process_result=False,
            )

    def unchanged(tree):
        return 0, "", "", tree

    no_image_api = NoImageApi(
        images={BASE_IMAGE: {"/repo/original.txt": b"original\n"}},
        tags={"swerebenchv2/example:1": BASE_IMAGE},
        handlers={"no image": unchanged},
    )
    executor, _, _ = _executor(tmp_path / "no-image", module, no_image_api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )
    receipt = await executor.run(base, "no image", timeout_s=10)
    assert receipt.image_before == receipt.image_after == base.head == BASE_IMAGE

    failed_api = FailedApi(
        images={BASE_IMAGE: {"/repo/original.txt": b"original\n"}},
        tags={"swerebenchv2/example:1": BASE_IMAGE},
        handlers={"fail": unchanged},
    )
    failed, _, failed_sink = _executor(tmp_path / "failed", module, failed_api)
    failed_base = await failed.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )
    with pytest.raises(RuntimeError, match="platform capacity unavailable"):
        await failed.run(failed_base, "fail", timeout_s=10)
    assert failed_base.head == BASE_IMAGE
    assert failed_sink.receipts == []


async def test_run_preserves_platform_timeout_state(tmp_path):
    module = _module()
    api_module = _api_module()

    class TimedOutApi(api_module.FakeTokenFactorySandboxApi):
        async def run(self, **kwargs):
            result = await super().run(**kwargs)
            return replace(
                result,
                exit_code=None,
                status="FAILED",
                timed_out=True,
                has_process_result=True,
            )

    def unchanged(tree):
        return 0, "partial output\n", "", tree

    api = TimedOutApi(
        images={BASE_IMAGE: {"/repo/original.txt": b"original\n"}},
        tags={"swerebenchv2/example:1": BASE_IMAGE},
        handlers={"timeout": unchanged},
    )
    executor, _, _ = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )

    receipt = await executor.run(base, "timeout", timeout_s=10)

    assert receipt.exit_code is None
    assert receipt.timed_out is True
    assert receipt.stdout_tail == "partial output\n"


async def test_run_writes_full_combined_log_digest_and_caps_separate_tails(tmp_path):
    module = _module()
    stdout = "o" * 7_000
    stderr = "e" * 7_100

    def noisy(tree):
        return 9, stdout, stderr, tree

    executor, _, _ = _executor(
        tmp_path,
        module,
        _fake(handlers={"noisy": noisy}),
    )
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )

    receipt = await executor.run(base, "noisy", timeout_s=10)

    complete = (stdout + stderr).encode()
    assert receipt.exit_code == 9
    assert receipt.stdout_tail == "o" * 6_000
    assert receipt.stderr_tail == "e" * 6_000
    assert Path(receipt.log_path).read_bytes() == complete
    assert receipt.stdout_sha256 == hashlib.sha256(complete).hexdigest()


async def test_write_then_read_round_trips_through_busybox_and_creates_parent(tmp_path):
    module = _module()
    content = "VALUE = 1\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    incoming = f"/opt/receipts/incoming/{digest}"
    target = "/repo/pkg/deep/new.py"
    command = (
        "/opt/receipts-bin/busybox sh -c "
        f"'mkdir -p /repo/pkg/deep && cp {incoming} {target}'"
    )
    api = _fake(handlers={command: _copy_handler(incoming, target)})
    executor, _, _ = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )

    receipt = await executor.write_file(base, "pkg/deep/new.py", content)

    assert receipt.kind == "write" and receipt.path == "pkg/deep/new.py"
    assert receipt.exit_code == 0
    assert receipt.stdout_sha256 == digest
    assert await executor.read_file(base, "pkg/deep/new.py", 7) == "VALUE ="
    call = next(call for call in api.calls if call["method"] == "run")
    assert call["command"] == command
    assert set(call["files"]) == {
        "/opt/receipts-bin/busybox",
        "/opt/receipts/receipts_pytest.py",
        incoming,
    }
    assert call["files"][incoming]["mode"] == "0644"


async def test_scratch_write_works_and_refused_paths_emit_refusal_receipts(tmp_path):
    module = _module()
    content = "print('probe')\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    incoming = f"/opt/receipts/incoming/{digest}"
    target = "/tmp/probe.py"
    command = (
        "/opt/receipts-bin/busybox sh -c "
        f"'mkdir -p /tmp && cp {incoming} {target}'"
    )
    api = _fake(handlers={command: _copy_handler(incoming, target)})
    executor, _, _ = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )

    assert executor.scratch_path(base) == "/tmp"
    written = await executor.write_file(base, target, content)
    refused = [
        await executor.write_file(base, path, "refused\n")
        for path in ("../x", "/etc/x", "/tmp")
    ]

    assert written.exit_code == 0
    assert await executor.read_file(base, target, 100) == content
    assert all(receipt.exit_code == 1 for receipt in refused)
    assert all("outside" in receipt.stderr_tail for receipt in refused)
    assert [
        await executor.read_file(base, path, 100)
        for path in ("../x", "/etc/x", "/tmp")
    ] == ["", "", ""]


async def test_read_file_lists_directories_sorted_and_caps_bytes(tmp_path):
    module = _module()
    api = _fake(
        tree={
            "/repo/listing/z.py": b"z\n",
            "/repo/listing/sub/nested.py": b"nested\n",
            "/repo/listing/a.py": b"abcdef",
        },
    )
    executor, _, _ = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )

    assert await executor.read_file(base, "listing", 100) == "a.py\nsub/\nz.py\n"
    assert await executor.read_file(base, "listing/a.py", 3) == "abc"
    assert await executor.read_file(base, "missing", 100) == ""
    with pytest.raises(ValueError, match="non-negative"):
        await executor.read_file(base, "listing/a.py", -1)


async def test_read_file_treats_a_listing_404_as_missing(tmp_path):
    module = _module()
    api_module = _api_module()

    class Listing404Api(api_module.FakeTokenFactorySandboxApi):
        async def list_files(self, image_uuid, path):
            raise api_module.TokenFactoryApiError(
                404,
                "GET",
                f"/v1/inspect/{image_uuid}/list",
                "not found",
            )

    api = Listing404Api(
        images={BASE_IMAGE: {"/repo/original.txt": b"original\n"}},
        tags={"swerebenchv2/example:1": BASE_IMAGE},
    )
    executor, _, _ = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )

    assert await executor.read_file(base, "missing", 100) == ""


async def test_checkpoint_and_late_forks_use_immutable_image_with_expected_ids(tmp_path):
    module = _module()
    content = "agent only\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    incoming = f"/opt/receipts/incoming/{digest}"
    target = "/repo/agent.txt"
    command = (
        "/opt/receipts-bin/busybox sh -c "
        f"'mkdir -p /repo && cp {incoming} {target}'"
    )
    executor, _, _ = _executor(
        tmp_path,
        module,
        _fake(handlers={command: _copy_handler(incoming, target)}),
    )
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )
    checkpoint = await executor.checkpoint(base)
    (candidate,) = await executor.fork(checkpoint, 1, prefix="c")
    await executor.write_file(candidate, "agent.txt", content)
    (witness,) = await executor.fork(checkpoint, 1, prefix="w")
    (official,) = await executor.fork(checkpoint, 1, prefix="official")

    assert checkpoint.id == checkpoint.parent == checkpoint.digest == BASE_IMAGE
    assert (candidate.id, witness.id, official.id) == ("c1", "w1", "official1")
    assert witness.head == witness.origin == checkpoint.id
    assert await executor.read_file(candidate, "agent.txt", 100) == content
    assert await executor.read_file(witness, "agent.txt", 100) == ""
    assert await executor.read_file(official, "agent.txt", 100) == ""


async def test_snapshot_returns_sha_from_daytona_git_command(tmp_path):
    module = _module()
    sha = "a" * 40
    command = (
        "git add -A && git -c user.name=receipts "
        "-c user.email=receipts@localhost commit -q --allow-empty "
        '-m "receipts snapshot" && git rev-parse HEAD'
    )

    def snapshot(tree):
        return 0, f"commit output\n{sha}\n", "", tree

    executor, api, sink = _executor(
        tmp_path,
        module,
        _fake(handlers={command: snapshot}),
    )
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )

    receipt = await executor.snapshot(base)

    assert receipt.snapshot_sha == sha
    assert receipt.cmd == command
    assert sink.receipts == [receipt]
    assert next(call for call in api.calls if call["method"] == "run")["command"] == command


async def test_run_pytest_uses_trusted_runner_downloads_result_junit_and_digest(
    tmp_path,
):
    module = _module()
    repository = tmp_path / "repository"
    (repository / "tests").mkdir(parents=True)
    (repository / "tests" / "test_sample.py").write_text("def test_ok(): pass\n")
    (repository / ".git").mkdir()
    (repository / ".git" / "index").write_bytes(b"root git metadata")
    (repository / "pkg" / ".git").mkdir(parents=True)
    (repository / "pkg" / ".git" / "index").write_bytes(b"nested git metadata")

    report = "/opt/receipts/reports/base-1.xml"
    command = (
        "/opt/receipts-bin/busybox mkdir -p /opt/receipts/reports && "
        "python3 -I /opt/receipts/receipts_pytest.py "
        f"tests/test_sample.py::test_ok {PYTEST_FLAGS} --junitxml={report}"
    )

    def pytest_run(tree):
        tree[report] = _junit_xml()
        tree.update(_fixture_tree(repository))
        return 0, "tests/test_sample.py::test_ok PASSED\n", "", tree

    api = _archive_fake(repository, handlers={command: pytest_run})
    executor, _, _ = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(
            image="swerebenchv2/example:1",
            workdir="/repo",
            python="python3",
        ),
    )

    receipt = await executor.run_pytest(
        base,
        "tests/test_sample.py::test_ok",
        timeout_s=37,
        kind="verification",
    )

    from receipts.sandbox.daytona import _tree_digest

    without_git = tmp_path / "without-git"
    shutil.copytree(repository, without_git, symlinks=True)
    shutil.rmtree(without_git / ".git")
    shutil.rmtree(without_git / "pkg" / ".git")
    expected_digest = _tree_digest(repository)
    assert expected_digest == _tree_digest(without_git)
    run_calls = [call for call in api.calls if call["method"] == "run"]
    assert run_calls[0]["command"] == command
    assert run_calls[0]["env"] == {"PYTEST_ADDOPTS": "", "PYTEST_PLUGINS": ""}
    assert run_calls[0]["image"] == BASE_IMAGE
    assert run_calls[1]["image"] == receipt.image_after
    assert run_calls[1]["disposable"] is False
    assert receipt.kind == "verification" and receipt.exit_code == 0
    assert receipt.junit is not None
    assert receipt.junit.passed == ["tests/test_sample.py::test_ok"]
    assert receipt.tree_digest == expected_digest
    assert receipt.tree_download_s is not None and receipt.tree_download_s >= 0
    assert receipt.image_before == BASE_IMAGE
    assert receipt.image_after == base.head
    assert run_calls[1]["image"] == base.head
    report_download = next(
        call
        for call in api.calls
        if call["method"] == "download" and call["path"] == report
    )
    assert report_download["image"] == receipt.image_after
    archive_download = next(
        call
        for call in api.calls
        if call["method"] == "download" and call["path"].endswith(".tar")
    )
    assert archive_download["image"] != base.head


async def test_run_pytest_returns_none_when_result_image_has_no_junit(tmp_path):
    module = _module()
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "module.py").write_text("VALUE = 1\n")
    report = "/opt/receipts/reports/base-1.xml"
    command = (
        "/opt/receipts-bin/busybox mkdir -p /opt/receipts/reports && "
        "python -I /opt/receipts/receipts_pytest.py "
        f"tests/missing.py {PYTEST_FLAGS} --junitxml={report}"
    )

    def missing_report(tree):
        return 4, "", "collection failed\n", tree

    api = _archive_fake(repository, handlers={command: missing_report})
    executor, _, _ = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )

    receipt = await executor.run_pytest(base, "tests/missing.py", timeout_s=30)

    assert receipt.exit_code == 4
    assert receipt.junit is None
    assert receipt.tree_digest is not None
    assert base.head == receipt.image_after


@pytest.mark.parametrize(
    ("member", "content"),
    [
        (tarfile.TarInfo("../x"), b"escape"),
        (tarfile.TarInfo("/abs"), b"absolute"),
        (_tar_info("device", tarfile.CHRTYPE), b""),
        (_tar_info("fifo", tarfile.FIFOTYPE), b""),
        (
            _tar_info("hardlink", tarfile.LNKTYPE, linkname="../outside"),
            b"",
        ),
    ],
)
def test_safe_archive_extraction_refuses_unsafe_members(tmp_path, member, content):
    module = _module()
    archive = _tar_with_members([(member, content)])

    with pytest.raises(OSError, match="unsafe Token Factory archive"):
        module._safe_extract_tar(archive, tmp_path / "out", size_cap_bytes=len(archive))


def test_safe_archive_extraction_refuses_writes_through_archive_symlink(tmp_path):
    module = _module()
    link = tarfile.TarInfo("linked")
    link.type = tarfile.SYMTYPE
    link.linkname = "../outside"
    child = tarfile.TarInfo("linked/file.txt")
    archive = _tar_with_members([(child, b"escape"), (link, b"")])

    with pytest.raises(OSError, match="passes through symlink"):
        module._safe_extract_tar(archive, tmp_path / "out", size_cap_bytes=len(archive))


def test_safe_archive_extraction_enforces_cap_and_keeps_outside_symlink_literal(
    tmp_path,
):
    module = _module()
    link = tarfile.TarInfo("outside-link")
    link.type = tarfile.SYMTYPE
    link.linkname = "../../outside"
    archive = _tar_with_members([(link, b"")])

    with pytest.raises(OSError, match="size cap"):
        module._safe_extract_tar(
            archive,
            tmp_path / "too-large",
            size_cap_bytes=len(archive) - 1,
        )
    module._safe_extract_tar(
        archive,
        tmp_path / "extracted",
        size_cap_bytes=len(archive),
    )

    extracted = tmp_path / "extracted" / "outside-link"
    assert extracted.is_symlink()
    assert os.readlink(extracted) == "../../outside"


async def test_patch_matches_trusted_staging_preserves_symlinks_and_caches_checkpoint(
    tmp_path,
):
    module = _module()
    checkpoint_tree = tmp_path / "checkpoint"
    (checkpoint_tree / "src").mkdir(parents=True)
    (checkpoint_tree / "tests").mkdir()
    (checkpoint_tree / "src" / "app.py").write_text("VALUE = 1\n")
    (checkpoint_tree / "src" / "delete.py").write_text("DELETE = True\n")
    (checkpoint_tree / "tests" / "test_guard.py").write_text("def test_old(): pass\n")
    (checkpoint_tree / "space name.txt").write_text("before\n")
    (checkpoint_tree / "link.py").symlink_to("src/app.py")
    snapshot_sha = _init_repo(checkpoint_tree)

    agent_tree = tmp_path / "agent"
    shutil.copytree(checkpoint_tree, agent_tree, symlinks=True)
    (agent_tree / "src" / "app.py").write_text("VALUE = 2\n")
    (agent_tree / "src" / "new.py").write_text("NEW = True\n")
    (agent_tree / "src" / "delete.py").unlink()
    (agent_tree / "tests" / "test_guard.py").write_text("def test_new(): pass\n")
    (agent_tree / "space name.txt").write_text("after\n")
    (agent_tree / "outside-link").symlink_to("../../outside")

    expected_tree = tmp_path / "expected"
    shutil.copytree(checkpoint_tree, expected_tree, symlinks=True)
    mirror_worktree(agent_tree, expected_tree)
    subprocess.run(["git", "add", "-A"], cwd=expected_tree, check=True)
    expected_patch = subprocess.run(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            snapshot_sha,
        ],
        cwd=expected_tree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    def mutate(tree):
        tree.update(_fixture_tree(agent_tree))
        return 0, "", "", tree

    api = _archive_fake(checkpoint_tree, handlers={"mutate agent": mutate})
    executor, _, _ = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )
    checkpoint = await executor.checkpoint(base)
    (agent,) = await executor.fork(checkpoint, 1, prefix="agent")
    await executor.run(agent, "mutate agent", timeout_s=30)

    receipt = await executor.patch(agent, snapshot_sha)
    second = await executor.patch(agent, snapshot_sha)

    from receipts.sandbox.daytona import _tree_digest

    assert receipt.exit_code == second.exit_code == 0
    assert receipt.diff is not None and second.diff is not None
    assert Path(receipt.diff.patch_path).read_text() == expected_patch
    assert Path(second.diff.patch_path).read_text() == expected_patch
    assert receipt.diff.patch_sha256 == hashlib.sha256(expected_patch.encode()).hexdigest()
    assert receipt.patch_sha256 == receipt.diff.patch_sha256
    assert receipt.snapshot_sha == snapshot_sha
    assert receipt.tree_digest == _tree_digest(agent_tree)
    assert set(receipt.dropped_paths) == {"outside-link", "tests/test_guard.py"}
    changed = {item.path: item.status for item in receipt.diff.files}
    assert changed["src/app.py"] == "modified"
    assert changed["src/new.py"] == "added"
    assert changed["src/delete.py"] == "deleted"
    assert changed["space name.txt"] == "modified"
    tar_calls = [
        call
        for call in api.calls
        if call["method"] == "run"
        and call["command"].startswith("/opt/receipts-bin/busybox tar ")
    ]
    checkpoint_fetches = [
        call
        for call in tar_calls
        if call["image"] == checkpoint.id and "--exclude=./.git" not in call["command"]
    ]
    assert len(checkpoint_fetches) == 1
    assert len([call for call in tar_calls if "--exclude=./.git" in call["command"]]) == 2
    assert agent.head == receipt.image_before == receipt.image_after
    assert second.image_before == second.image_after == agent.head


async def test_apply_patch_injects_exact_bytes_uses_upstream_flags_and_moves_head(
    tmp_path,
):
    module = _module()
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "original.txt").write_text("original\n")
    _init_repo(repository)
    applied = tmp_path / "applied"
    shutil.copytree(repository, applied, symlinks=True)
    (applied / "original.txt").write_text("changed\n")
    patch_text = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-renames"],
        cwd=applied,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    digest = hashlib.sha256(patch_text.encode()).hexdigest()
    remote_patch = f"/opt/receipts/incoming/{digest}.diff"
    command = (
        "git update-index -q --refresh; "
        f"git apply {GIT_APPLY_FLAGS} {remote_patch}"
    )

    def apply(tree):
        assert tree[remote_patch] == patch_text.encode()
        tree.update(_fixture_tree(applied))
        return 0, "Checking patch original.txt...\nApplied patch original.txt cleanly.\n", "", tree

    api = _archive_fake(repository, handlers={command: apply})
    executor, _, _ = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )
    checkpoint = await executor.checkpoint(base)
    (witness,) = await executor.fork(checkpoint, 1, prefix="w")
    before = witness.head

    receipt = await executor.apply_patch(witness, patch_text)

    from receipts.sandbox.daytona import _tree_digest

    run_calls = [call for call in api.calls if call["method"] == "run"]
    assert run_calls[0]["command"] == command
    assert set(run_calls[0]["files"]) == {
        "/opt/receipts-bin/busybox",
        "/opt/receipts/receipts_pytest.py",
        remote_patch,
    }
    assert receipt.kind == "apply" and receipt.exit_code == 0
    assert receipt.patch_sha256 == digest
    assert receipt.image_before == before
    assert receipt.image_after == witness.head != before
    assert run_calls[1]["image"] == witness.head
    assert run_calls[1]["image"] == receipt.image_after
    assert receipt.tree_digest == _tree_digest(applied)


async def test_sandbox_usage_records_each_run_cost_and_close_writes_empty_manifest(
    tmp_path,
):
    module = _module()
    api_module = _api_module()

    class CostApi(api_module.FakeTokenFactorySandboxApi):
        async def run(self, **kwargs):
            result = await super().run(**kwargs)
            number = len([call for call in self.calls if call["method"] == "run"])
            return replace(result, duration_s=number / 2, cost=number / 100)

    def unchanged(tree):
        return 0, "", "", tree

    api = CostApi(
        images={BASE_IMAGE: {"/repo/original.txt": b"original\n"}},
        tags={"swerebenchv2/example:1": BASE_IMAGE},
        handlers={"one": unchanged, "two": unchanged},
    )
    executor, _, _ = _executor(tmp_path, module, api)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cleanup_manifest = run_dir / "cleanup.json"
    (run_dir / "cost.json").write_text("{}\n", encoding="utf-8")
    executor.cleanup_manifest = cleanup_manifest
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )
    await executor.run(base, "one", timeout_s=10)
    await executor.run(base, "two", timeout_s=10)

    await executor.close()
    usage = executor.sandbox_usage()

    assert cleanup_manifest.read_text(encoding="utf-8") == "[]\n"
    assert len(usage) == 2
    assert [item["operation_id"] for item in usage] == [
        "fake-operation-1",
        "fake-operation-2",
    ]
    assert [item["branch"] for item in usage] == ["base", "base"]
    assert [item["duration_s"] for item in usage] == [0.5, 1.0]
    assert [item["cost"] for item in usage] == [0.01, 0.02]
    assert all(item["seconds"] >= 0 for item in usage)
    for item in usage:
        assert datetime.fromisoformat(item["created_at"]) <= datetime.fromisoformat(
            item["deleted_at"],
        )
    persisted_cost = json.loads((run_dir / "cost.json").read_text(encoding="utf-8"))
    assert persisted_cost["sandbox_usage"] == usage
    assert [call["method"] for call in api.calls].count("aclose") == 1


async def test_release_forgets_branch(tmp_path):
    module = _module()
    executor, _, _ = _executor(tmp_path, module)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )

    await executor.release(base)
    await executor.release(base)
    with pytest.raises(RuntimeError, match="released|unknown"):
        executor.scratch_path(base)
    with pytest.raises(RuntimeError, match="only be called once"):
        await executor.prepare(
            ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
        )


async def test_api_key_is_absent_from_executor_receipts_logs_and_reprs(tmp_path):
    module = _module()
    secret = "tf-secret-that-must-not-leak"

    def harmless(tree):
        return 0, "ordinary output\n", "", tree

    api = _fake(handlers={"harmless": harmless})
    api._api_key = secret
    executor, _, sink = _executor(tmp_path, module, api)
    base = await executor.prepare(
        ImageSource(image="swerebenchv2/example:1", workdir="/repo"),
    )
    await executor.run(base, "harmless", timeout_s=10)

    rendered = repr(executor) + repr(api)
    rendered += "".join(receipt.model_dump_json() for receipt in sink.receipts)
    rendered += "".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (tmp_path / "executor").rglob("*")
        if path.is_file()
    )
    assert secret not in rendered


def test_default_output_limit_is_below_the_platform_cap(tmp_path):
    module = importlib.import_module("receipts.sandbox.tokenfactory")
    executor = module.TokenFactoryExecutor(
        tmp_path / "executor", MemorySink(), "run", object(), busybox=b"busybox",
    )

    assert executor.truncate_output_at < 10 * 1024 * 1024


async def test_truncated_output_leaves_no_full_log_so_grading_fails_closed(tmp_path):
    module = importlib.import_module("receipts.sandbox.tokenfactory")
    api_module = importlib.import_module("receipts.sandbox.tokenfactory_api")
    api = api_module.FakeTokenFactorySandboxApi(
        images={"img": {}},
        tags={"repo/x:1": "img"},
        handlers={"loud": lambda tree: (0, "PASSED a\n" * 100, "", tree)},
    )
    executor = module.TokenFactoryExecutor(
        tmp_path / "executor", MemorySink(), "run", api, busybox=b"busybox", truncate_output_at=100,
    )
    base = await executor.prepare(ImageSource(image="repo/x:1", workdir="/repo"))

    receipt = await executor.run(base, "loud", 30)

    assert receipt.log_path is None
    assert "truncated" in receipt.stderr_tail


async def test_empty_patch_is_a_successful_apply_without_running_git(tmp_path):
    """Screening grades an empty patch; like Daytona, nothing is applied."""

    module = _module()
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "original.txt").write_text("original\n")
    _init_repo(repository)
    api = _archive_fake(repository, handlers={})
    executor, _, _ = _executor(tmp_path, module, api)
    base = await executor.prepare(ImageSource(image="swerebenchv2/example:1", workdir="/repo"))
    checkpoint = await executor.checkpoint(base)
    (witness,) = await executor.fork(checkpoint, 1, prefix="official")
    before = witness.head

    receipt = await executor.apply_patch(witness, "")

    assert receipt.kind == "apply"
    assert receipt.exit_code == 0
    assert receipt.patch_sha256 == hashlib.sha256(b"").hexdigest()
    assert receipt.image_before == before == receipt.image_after == witness.head
    assert not any("git apply" in call.get("command", "") for call in api.calls if call["method"] == "run")
