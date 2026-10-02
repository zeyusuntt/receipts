from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


def _watch_module():
    try:
        return importlib.import_module("receipts.pilot.watch")
    except ModuleNotFoundError:
        pytest.fail("receipts.pilot.watch is missing")


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _record(
    instance_id: str,
    status: str,
    *,
    agreement: str | None = None,
    verified: bool = False,
) -> dict:
    return {
        "instance_id": instance_id,
        "status": status,
        "reason": "temporary outage" if status == "infra_error" else None,
        "run_dir": f"runs/{instance_id}",
        "attempts": [
            {
                "gate_status": "PASS",
                "agreement": agreement,
            },
        ] if agreement is not None else [],
        "final": {"verified_fix": verified} if status == "ran" else None,
    }


def test_transient_infrastructure_record_does_not_stop(tmp_path: Path):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1" / "record.json",
        _record("candidate-1", "infra_error"),
    )

    snapshot = watch.snapshot_directory(tmp_path)

    assert watch.decide(snapshot) is None


def test_final_infrastructure_marker_stops(tmp_path: Path):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1" / "final_infra_error.json",
        {
            "instance_id": "candidate-1",
            "runs": 3,
            "reason": "provider unavailable",
            "written_at": "2026-10-02T12:00:00+00:00",
        },
    )

    reason = watch.decide(watch.snapshot_directory(tmp_path))

    assert reason is not None
    assert "candidate-1" in reason
    assert "provider unavailable" in reason


def test_gate_looser_record_stops(tmp_path: Path):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1" / "record.json",
        _record("candidate-1", "ran", agreement="gate_looser"),
    )

    reason = watch.decide(watch.snapshot_directory(tmp_path))

    assert reason is not None
    assert "gate_looser" in reason
    assert "candidate-1" in reason


def test_four_archived_infrastructure_records_stop_retry_loop(tmp_path: Path):
    watch = _watch_module()
    for number in range(1, 5):
        _write_json(
            tmp_path / "candidate-1" / f"record.infra-{number}.json",
            _record("candidate-1", "infra_error"),
        )

    reason = watch.decide(watch.snapshot_directory(tmp_path))

    assert reason is not None
    assert "retry loop" in reason
    assert "4 archived" in reason


def test_normal_records_only_produce_progress_lines(tmp_path: Path):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1" / "record.json",
        _record("candidate-1", "ran", agreement="agree_pass", verified=True),
    )
    _write_json(
        tmp_path / "candidate-2" / "record.json",
        _record("candidate-2", "excluded"),
    )
    snapshot = watch.snapshot_directory(tmp_path)

    lines, seen = watch.newly_finished_lines(snapshot, frozenset())

    assert watch.decide(snapshot) is None
    assert len(lines) == 2
    assert "candidate-1 ran" in lines[0]
    assert "gates=['PASS']" in lines[0]
    assert "agree=['agree_pass']" in lines[0]
    assert "verified=True" in lines[0]
    assert "candidate-2 excluded" in lines[1]
    assert len(seen) == 2
    assert watch.newly_finished_lines(snapshot, seen)[0] == ()


def test_archiving_an_observed_record_does_not_print_it_twice(tmp_path: Path):
    watch = _watch_module()
    current = tmp_path / "candidate-1" / "record.json"
    archived = tmp_path / "candidate-1" / "record.infra-1.json"
    _write_json(current, _record("candidate-1", "infra_error"))
    lines, seen = watch.newly_finished_lines(
        watch.snapshot_directory(tmp_path),
        frozenset(),
    )
    current.replace(archived)

    archived_lines, _ = watch.newly_finished_lines(
        watch.snapshot_directory(tmp_path),
        seen,
    )

    assert len(lines) == 1
    assert archived_lines == ()
