"""Persistence helpers for one portable Receipts run directory."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from pydantic import BaseModel

from receipts.models import Receipt


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


class RunDirectory:
    """Write the stable run bundle layout from design section 7.7."""

    def __init__(self, root: Path) -> None:
        self.root = root
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(f"run directory is not empty: {root}")
        (root / "agent").mkdir(parents=True, exist_ok=True)
        (root / "attempts").mkdir(exist_ok=True)
        (root / "reverify").mkdir(exist_ok=True)

    def path(self, relative: str) -> Path:
        candidate = PurePosixPath(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"run artifact path must be relative: {relative}")
        return self.root.joinpath(*candidate.parts)

    def write_json(self, relative: str, value: Any) -> Path:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                _json_value(value),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def write_text(self, relative: str, value: str) -> Path:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def write_bytes(self, relative: str, value: bytes) -> Path:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def write_receipts(
        self,
        relative: str,
        receipts: Iterable[Receipt],
    ) -> Path:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as writer:
            for receipt in receipts:
                writer.write(receipt.model_dump_json() + "\n")
        return path

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


__all__ = ["RunDirectory"]
