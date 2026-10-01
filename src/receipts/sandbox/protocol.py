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

from pydantic import BaseModel

from receipts.models import Branch, Checkpoint, Receipt, ReceiptKind


class RepoAtCommit(BaseModel):
    url: str
    commit: str
    install_cmd: str


Source = RepoAtCommit


class Executor(Protocol):
    async def prepare(self, source: Source) -> Branch: ...
    async def snapshot(self, branch: Branch) -> Receipt: ...
    async def checkpoint(self, branch: Branch) -> Checkpoint: ...
    async def fork(self, checkpoint: Checkpoint, n: int, prefix: str = "b") -> list[Branch]: ...
    async def run(self, branch: Branch, cmd: str, timeout_s: int) -> Receipt: ...
    async def run_pytest(self, branch: Branch, args: str, timeout_s: int, kind: ReceiptKind = "command") -> Receipt: ...
    async def read_file(self, branch: Branch, path: str, max_bytes: int) -> str: ...
    async def write_file(self, branch: Branch, path: str, content: str) -> Receipt: ...
    async def patch(self, branch: Branch, snapshot_sha: str) -> Receipt: ...
    async def apply_patch(self, branch: Branch, patch_text: str) -> Receipt: ...


PYTEST_FLAGS = "-o junit_family=xunit1 -p no:cacheprovider -q"
