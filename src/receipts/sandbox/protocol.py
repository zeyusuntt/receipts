"""The executor contract. The local executor (this plan) and the Token Factory
executor (Plan 2) both implement it; the gate and the agent only see this.

Design rules: the executor never sees a prompt; the model never sees a
Receipt object, only the `stdout_tail` the worker chooses to show it; every
method is async so two branches can run at once on a remote sandbox.

Known differences a remote implementation must document rather than hide:
`timeout_s` is capped by the platform (Token Factory: 3,600 s per operation);
`RepoAtCommit.url` must be a URL the sandbox can clone (a local path works
only for the local executor); `stdout_sha256` hashes the bytes the executor
received, which on Token Factory are truncated at 65,535 by default unless
the command redirects to a file, and receipts say which.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from receipts.models import Branch, Checkpoint, Receipt, ReceiptKind


class RepoAtCommit(BaseModel):
    url: str
    commit: str
    install_cmd: str


class ImageSource(BaseModel):
    image: str
    workdir: str
    python: str = "python"
    platform: str | None = None
    setup: list[str] = Field(default_factory=list)


Source = RepoAtCommit | ImageSource


class CheckpointTampered(Exception):
    def __init__(self, checkpoint_id: str) -> None:
        super().__init__(f"checkpoint {checkpoint_id} was modified after prepare")
        self.checkpoint_id = checkpoint_id
        self.patch_receipt: Receipt | None = None


class Executor(Protocol):
    async def prepare(self, source: Source) -> Branch: ...
    async def snapshot(self, branch: Branch) -> Receipt: ...
    async def checkpoint(self, branch: Branch) -> Checkpoint: ...
    async def fork(self, checkpoint: Checkpoint, n: int, prefix: str = "b") -> list[Branch]: ...
    async def release(self, branch: Branch) -> None: ...
    async def run(self, branch: Branch, cmd: str, timeout_s: int) -> Receipt: ...
    async def run_pytest(self, branch: Branch, args: str, timeout_s: int, kind: ReceiptKind = "command") -> Receipt: ...
    async def read_file(self, branch: Branch, path: str, max_bytes: int) -> str: ...
    async def write_file(self, branch: Branch, path: str, content: str) -> Receipt: ...
    async def patch(self, branch: Branch, snapshot_sha: str) -> Receipt: ...
    async def apply_patch(self, branch: Branch, patch_text: str) -> Receipt: ...


PYTEST_FLAGS = "-o junit_family=xunit1 -p no:cacheprovider -rA --continue-on-collection-errors"

# The flags SWE-rebench-V2 scripts/eval.py uses to apply a model patch. Witnesses and
# official grading apply patches the same way, so line-ending and whitespace differences
# between a patch and a file are tolerated exactly as the upstream grader tolerates them.
GIT_APPLY_FLAGS = "-v --3way --recount --ignore-space-change --whitespace=nowarn"

PYTEST_BOOTSTRAP = """\
import os
import sys

sys.dont_write_bytecode = True

import pytest

pytest_path = os.path.realpath(pytest.__file__)
worktree = os.path.realpath(os.getcwd())
try:
    untrusted = os.path.commonpath((worktree, pytest_path)) == worktree
except ValueError:
    untrusted = False
if untrusted:
    print(f"receipts: untrusted pytest at {pytest_path}", file=sys.stderr)
    raise SystemExit(4)
# Like the instance's own `pytest` command, do not put the repository root on
# sys.path: a new top-level package in a patch must not shadow the installed one.


class _ReceiptsDirs:
    # Records pytest's rootdir and invocation dir, which junit xml leaves out.

    rootdir = None
    invocation = None

    def pytest_configure(self, config):
        root = getattr(config, "rootpath", None) or getattr(config, "rootdir", None)
        params = getattr(config, "invocation_params", None)
        invocation = getattr(params, "dir", None) if params is not None else getattr(config, "invocation_dir", None)
        self.rootdir = os.path.realpath(str(root)) if root is not None else None
        self.invocation = os.path.realpath(str(invocation)) if invocation is not None else worktree


dirs = _ReceiptsDirs()
code = pytest.main(sys.argv[1:], plugins=[dirs])

xml_path = None
args = sys.argv[1:]
for index, arg in enumerate(args):
    for option in ("--junitxml", "--junit-xml"):
        if arg.startswith(option + "="):
            xml_path = arg.split("=", 1)[1]
        elif arg == option and index + 1 < len(args):
            xml_path = args[index + 1]
if xml_path and dirs.rootdir and os.path.isfile(xml_path):
    try:
        import xml.etree.ElementTree as ET

        tree = ET.parse(xml_path)
        for suite in tree.getroot().iter("testsuite"):
            properties = suite.find("properties")
            if properties is None:
                properties = ET.Element("properties")
                suite.insert(0, properties)
            ET.SubElement(properties, "property", name="receipts_rootdir", value=dirs.rootdir)
            ET.SubElement(properties, "property", name="receipts_invocation_dir", value=dirs.invocation)
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    except Exception as exc:
        print(f"receipts: could not annotate junit: {exc}", file=sys.stderr)
raise SystemExit(code)
"""
