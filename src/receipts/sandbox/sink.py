"""Where receipts go. A receipt is written once, complete, the moment it is
final, and flushed, so a UI can tail the file while a branch is still running.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from receipts.models import Receipt


class ReceiptSink(Protocol):
    def write(self, receipt: Receipt) -> None: ...


class MemorySink:
    def __init__(self) -> None:
        self.receipts: list[Receipt] = []

    def write(self, receipt: Receipt) -> None:
        self.receipts.append(receipt)


class RunSink:
    """One receipts.jsonl per branch under run_dir/branches/<branch_id>/."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    def path_for(self, branch_id: str) -> Path:
        return self.run_dir / "branches" / branch_id / "receipts.jsonl"

    def write(self, receipt: Receipt) -> None:
        path = self.path_for(receipt.branch_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(receipt.model_dump_json() + "\n")
            fh.flush()
