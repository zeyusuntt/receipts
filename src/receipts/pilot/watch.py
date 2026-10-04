"""Watch a pilot directory and stop its process only on terminal failures."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import time
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable


_MAX_INFRASTRUCTURE_RUNS = 3
_ARCHIVE_NAME = re.compile(r"record\.infra-[0-9]+\.json\Z")
_INTERRUPTED_NAME = re.compile(r"record\.interrupted-[0-9]+\.json\Z")
FileVersion = tuple[str, str]


@dataclass(frozen=True)
class SnapshotFile:
    relative_path: str
    digest: str
    value: dict[str, Any] | None

    @property
    def version(self) -> FileVersion:
        if self.value is not None:
            instance_id = self.value.get("instance_id")
            run_dir = self.value.get("run_dir")
            if isinstance(instance_id, str) and isinstance(run_dir, str):
                return instance_id, run_dir
        return self.relative_path, self.digest


@dataclass(frozen=True)
class DirectorySnapshot:
    files: tuple[SnapshotFile, ...]


def _read_snapshot_file(root: Path, path: Path) -> SnapshotFile | None:
    try:
        content = path.read_bytes()
    except OSError:
        return None
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        value = None
    if not isinstance(value, dict):
        value = None
    return SnapshotFile(
        relative_path=path.relative_to(root).as_posix(),
        digest=hashlib.sha256(content).hexdigest(),
        value=value,
    )


def snapshot_directory(pilot_dir: Path) -> DirectorySnapshot:
    """Read the record files needed by the pure watchdog decision functions."""

    paths = sorted(pilot_dir.glob("*/record.json"))
    paths.extend(sorted(pilot_dir.glob("*/record.infra-*.json")))
    paths.extend(sorted(pilot_dir.glob("*/record.interrupted-*.json")))
    paths.extend(sorted(pilot_dir.glob("*/final_infra_error.json")))
    files = tuple(
        snapshot
        for path in sorted(paths)
        if (snapshot := _read_snapshot_file(pilot_dir, path)) is not None
    )
    return DirectorySnapshot(files=files)


def _instance_id(item: SnapshotFile) -> str:
    if item.value is not None and isinstance(item.value.get("instance_id"), str):
        return item.value["instance_id"]
    return Path(item.relative_path).parent.name


def _model_spend(snapshot: DirectorySnapshot) -> Decimal:
    total = Decimal("0")
    for item in snapshot.files:
        name = Path(item.relative_path).name
        if (
            item.value is None
            or not (
                name == "record.json"
                or _ARCHIVE_NAME.fullmatch(name)
                or _INTERRUPTED_NAME.fullmatch(name)
            )
        ):
            continue
        cost = item.value.get("cost")
        if not isinstance(cost, dict):
            continue
        value = cost.get("model_dollars")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            dollars = Decimal(str(value))
        except InvalidOperation:
            continue
        if dollars.is_finite():
            total += dollars
    return total


def _format_dollars(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." not in rendered:
        return f"{rendered}.00"
    whole, fraction = rendered.split(".", maxsplit=1)
    return f"{whole}.{fraction.ljust(2, '0')}"


def decide(
    snapshot: DirectorySnapshot,
    *,
    max_infrastructure_runs: int = _MAX_INFRASTRUCTURE_RUNS,
    model_budget_usd: float | None = None,
) -> str | None:
    """Return a stop reason for a directory snapshot, without performing I/O."""

    for item in snapshot.files:
        if Path(item.relative_path).name != "final_infra_error.json":
            continue
        instance_id = _instance_id(item)
        value = item.value or {}
        runs = value.get("runs", "unknown")
        reason = value.get("reason", "reason unavailable")
        return (
            f"final infrastructure error for {instance_id} after {runs} runs: "
            f"{reason}"
        )

    for item in snapshot.files:
        if Path(item.relative_path).name != "record.json" or item.value is None:
            continue
        attempts = item.value.get("attempts")
        if not isinstance(attempts, list):
            continue
        if any(
            isinstance(attempt, dict)
            and attempt.get("agreement") == "gate_looser"
            for attempt in attempts
        ):
            return f"gate_looser agreement for {_instance_id(item)}"

    archives = Counter(
        _instance_id(item)
        for item in snapshot.files
        if _ARCHIVE_NAME.fullmatch(Path(item.relative_path).name)
    )
    for instance_id, count in sorted(archives.items()):
        if count > max_infrastructure_runs:
            return (
                f"retry loop for {instance_id}: {count} archived infrastructure "
                "records"
            )
    if model_budget_usd is not None:
        budget = Decimal(str(model_budget_usd))
        total = _model_spend(snapshot)
        if total > budget:
            return (
                f"model spend ${_format_dollars(total)} exceeds budget "
                f"${_format_dollars(budget)}"
            )
    return None


def _record_line(item: SnapshotFile) -> str | None:
    path = Path(item.relative_path)
    if (
        item.value is None
        or not (
            path.name == "record.json"
            or _ARCHIVE_NAME.fullmatch(path.name)
        )
    ):
        return None
    record = item.value
    attempts = record.get("attempts")
    if not isinstance(attempts, list):
        attempts = []
    gate_statuses = [
        attempt.get("gate_status")
        for attempt in attempts
        if isinstance(attempt, dict)
    ]
    agreements = [
        attempt.get("agreement")
        for attempt in attempts
        if isinstance(attempt, dict)
    ]
    final = record.get("final")
    verified = final.get("verified_fix") if isinstance(final, dict) else None
    reason = record.get("reason") or ""
    prefix = "[retry archived] " if path.name != "record.json" else ""
    return (
        f"{prefix}{_instance_id(item)} {record.get('status')} {str(reason)[:80]} "
        f"gates={gate_statuses} agree={agreements} verified={verified}"
    )


def newly_finished_lines(
    snapshot: DirectorySnapshot,
    seen: frozenset[FileVersion],
) -> tuple[tuple[str, ...], frozenset[FileVersion]]:
    """Return progress lines and an updated immutable set of file versions."""

    observed = set(seen)
    lines: list[str] = []
    for item in snapshot.files:
        line = _record_line(item)
        if line is None:
            continue
        if item.version not in observed:
            lines.append(line)
        observed.add(item.version)
    return tuple(lines), frozenset(observed)


def _pid_exists(pid: int, kill: Callable[[int, int], None]) -> bool:
    try:
        kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def watch_pilot(
    pilot_dir: Path,
    pid: int,
    *,
    interval: float = 20.0,
    model_budget_usd: float | None = None,
    kill: Callable[[int, int], None] = os.kill,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Poll a pilot directory, stop on a terminal watchdog condition, and exit 0."""

    if pid <= 0:
        raise ValueError("PID must be positive")
    if interval <= 0:
        raise ValueError("--interval must be positive")

    snapshot = snapshot_directory(pilot_dir)
    acknowledged = frozenset(
        _instance_id(item)
        for item in snapshot.files
        if Path(item.relative_path).name == "final_infra_error.json"
    )
    if acknowledged:
        print(
            f"acknowledged final infrastructure errors: {sorted(acknowledged)}",
            flush=True,
        )
    _, seen = newly_finished_lines(snapshot, frozenset())
    while True:
        if not _pid_exists(pid, kill):
            print("pilot process exited", flush=True)
            return 0

        # Only final markers are acknowledged. Retain every record so spend,
        # gate disagreements, and retry loops still include these instances.
        pending = DirectorySnapshot(
            files=tuple(
                item for item in snapshot.files
                if not (
                    Path(item.relative_path).name == "final_infra_error.json"
                    and _instance_id(item) in acknowledged
                )
            ),
        )
        reason = decide(pending, model_budget_usd=model_budget_usd)
        if reason is not None:
            try:
                kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                print("pilot process exited", flush=True)
                return 0
            print(f"WATCHDOG: {reason}", flush=True)
            return 0

        sleep(interval)
        snapshot = snapshot_directory(pilot_dir)
        lines, seen = newly_finished_lines(snapshot, seen)
        for line in lines:
            print(line, flush=True)


__all__ = [
    "DirectorySnapshot",
    "FileVersion",
    "SnapshotFile",
    "decide",
    "newly_finished_lines",
    "snapshot_directory",
    "watch_pilot",
]
