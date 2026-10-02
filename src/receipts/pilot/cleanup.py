"""Find and retry durable Daytona snapshot cleanup manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Sequence

from pydantic import BaseModel


class CleanupEntry(BaseModel):
    id: str
    name: str
    created_at: str
    status: Literal["created", "deleted", "delete_failed"]
    error: str | None


class SnapshotDeleteApi(Protocol):
    async def delete_snapshot(self, snapshot: str, *, timeout_s: int) -> None: ...


@dataclass(frozen=True)
class CleanupItem:
    manifest: Path
    id: str
    name: str
    previous_status: str
    status: str
    error: str | None


@dataclass(frozen=True)
class CleanupResult:
    manifests: int
    pending: tuple[CleanupItem, ...]
    yes: bool

    @property
    def deleted(self) -> int:
        if not self.yes:
            return 0
        return sum(item.status == "deleted" for item in self.pending)

    @property
    def failed(self) -> int:
        if not self.yes:
            return 0
        return sum(item.status == "delete_failed" for item in self.pending)


def _manifest_paths(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.name == "cleanup.json" else []
    return sorted(root.rglob("cleanup.json"))


def _read_manifest(path: Path) -> list[CleanupEntry]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"cleanup manifest is not a JSON list: {path}")
    return [CleanupEntry.model_validate(entry) for entry in value]


def _write_manifest(path: Path, entries: Sequence[CleanupEntry]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            [entry.model_dump(mode="json") for entry in entries],
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _status_code(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None)
    return value if isinstance(value, int) else None


def _redact(value: str, secrets: Sequence[str]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


async def cleanup_manifests(
    root: Path,
    api: SnapshotDeleteApi | None,
    *,
    yes: bool,
    secrets: Sequence[str] = (),
) -> CleanupResult:
    """List pending snapshots and optionally retry each provider deletion."""

    paths = _manifest_paths(root)
    pending: list[CleanupItem] = []
    if yes and api is None:
        raise ValueError("a Daytona API is required with --yes")

    for path in paths:
        entries = _read_manifest(path)
        for index, entry in enumerate(entries):
            if entry.status == "deleted":
                continue
            previous_status = entry.status
            if yes:
                try:
                    assert api is not None
                    await api.delete_snapshot(entry.id, timeout_s=120)
                except Exception as exc:
                    if _status_code(exc) == 404:
                        entry.status = "deleted"
                        entry.error = None
                    else:
                        entry.status = "delete_failed"
                        entry.error = _redact(str(exc), secrets)
                else:
                    entry.status = "deleted"
                    entry.error = None
                entries[index] = entry
                _write_manifest(path, entries)
            pending.append(
                CleanupItem(
                    manifest=Path(_redact(str(path), secrets)),
                    id=_redact(entry.id, secrets),
                    name=_redact(entry.name, secrets),
                    previous_status=previous_status,
                    status=entry.status,
                    error=(
                        _redact(entry.error, secrets)
                        if entry.error is not None
                        else None
                    ),
                ),
            )
    return CleanupResult(manifests=len(paths), pending=tuple(pending), yes=yes)


def render_cleanup(result: CleanupResult) -> str:
    lines = []
    for item in result.pending:
        label = item.status.upper() if result.yes else "PENDING"
        line = (
            f"{label} manifest={item.manifest} id={item.id} name={item.name} "
            f"status={item.status}"
        )
        if item.error is not None:
            line += f" error={item.error}"
        lines.append(line)
    lines.append(
        "CLEANUP "
        f"manifests={result.manifests} pending={len(result.pending)} "
        f"deleted={result.deleted} failed={result.failed} "
        f"dry_run={'false' if result.yes else 'true'}",
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "CleanupEntry",
    "CleanupItem",
    "CleanupResult",
    "cleanup_manifests",
    "render_cleanup",
]
