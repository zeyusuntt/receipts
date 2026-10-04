from __future__ import annotations

import importlib
import json
import signal
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
    model_dollars: float = 0.0,
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
        "cost": {"model_dollars": model_dollars},
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


def test_model_spend_under_budget_does_not_stop(tmp_path: Path):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1" / "record.json",
        _record("candidate-1", "ran", model_dollars=0.75),
    )

    reason = watch.decide(
        watch.snapshot_directory(tmp_path),
        model_budget_usd=1.0,
    )

    assert reason is None


def test_model_spend_over_budget_stops_with_total_and_budget(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1" / "record.json",
        _record("candidate-1", "ran", model_dollars=0.75),
    )
    _write_json(
        tmp_path / "candidate-2" / "record.json",
        _record("candidate-2", "ran", model_dollars=0.50),
    )
    signals: list[tuple[int, int]] = []

    result = watch.watch_pilot(
        tmp_path,
        4321,
        interval=0.01,
        model_budget_usd=1.0,
        kill=lambda pid, sig: signals.append((pid, sig)),
        sleep=lambda _: pytest.fail("over-budget watch must stop before sleeping"),
    )

    assert result == 0
    assert signals == [(4321, 0), (4321, signal.SIGTERM)]
    assert capsys.readouterr().out == (
        "WATCHDOG: model spend $1.25 exceeds budget $1.00\n"
    )


def test_archived_records_count_toward_model_budget(tmp_path: Path):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1" / "record.infra-1.json",
        _record("candidate-1", "infra_error", model_dollars=0.60),
    )
    _write_json(
        tmp_path / "candidate-1" / "record.json",
        _record("candidate-1", "ran", model_dollars=0.50),
    )

    reason = watch.decide(
        watch.snapshot_directory(tmp_path),
        model_budget_usd=1.0,
    )

    assert reason == "model spend $1.10 exceeds budget $1.00"


def test_interrupted_archives_count_toward_model_budget(tmp_path: Path):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1" / "record.interrupted-1.json",
        _record("candidate-1", "interrupted", model_dollars=0.70),
    )
    _write_json(
        tmp_path / "candidate-1" / "record.json",
        _record("candidate-1", "ran", model_dollars=0.50),
    )

    reason = watch.decide(
        watch.snapshot_directory(tmp_path),
        model_budget_usd=1.0,
    )

    assert reason == "model spend $1.20 exceeds budget $1.00"


def test_interrupted_archives_do_not_count_as_infrastructure_retries(
    tmp_path: Path,
):
    watch = _watch_module()
    for number in range(1, 5):
        _write_json(
            tmp_path / "candidate-1" / f"record.interrupted-{number}.json",
            _record("candidate-1", "interrupted"),
        )

    assert watch.decide(watch.snapshot_directory(tmp_path)) is None


def test_no_model_budget_flag_does_not_stop_on_spend(tmp_path: Path):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1" / "record.json",
        _record("candidate-1", "ran", model_dollars=100.0),
    )

    reason = watch.decide(watch.snapshot_directory(tmp_path))

    assert reason is None


@pytest.mark.parametrize("malformed", [False, True])
def test_watch_acknowledges_existing_final_error_and_its_rewrites(
    tmp_path, capsys, malformed,
):
    watch = _watch_module()
    marker = tmp_path / "candidate-1" / "final_infra_error.json"
    _write_json(marker, {"instance_id": "candidate-1", "runs": 3, "reason": "old"})
    if malformed:
        marker.write_text("{partial", encoding="utf-8")
    signals = []
    polls = 0

    def kill(pid, sig):
        signals.append((pid, sig))
        if polls == 2:
            raise ProcessLookupError

    def sleep(_):
        nonlocal polls
        polls += 1
        _write_json(marker, {"instance_id": "candidate-1", "runs": 3, "reason": f"rewrite {polls}"})

    assert watch.watch_pilot(tmp_path, 4321, kill=kill, sleep=sleep) == 0
    assert polls == 2
    assert all(sig == 0 for _, sig in signals)
    output = capsys.readouterr().out
    assert output.count("acknowledged final infrastructure errors: ['candidate-1']") == 1
    assert "WATCHDOG:" not in output
    assert "pilot process exited" in output


def test_watch_stops_on_new_final_error_for_another_instance(tmp_path, capsys):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1/final_infra_error.json",
        {"instance_id": "candidate-1", "runs": 3, "reason": "old"},
    )
    signals = []
    polls = 0

    def sleep(_):
        nonlocal polls
        polls += 1
        assert polls == 1
        _write_json(
            tmp_path / "candidate-2/final_infra_error.json",
            {"instance_id": "candidate-2", "runs": 3, "reason": "new outage"},
        )

    assert watch.watch_pilot(
        tmp_path, 4321, kill=lambda pid, sig: signals.append((pid, sig)), sleep=sleep,
    ) == 0
    assert polls == 1
    assert signals == [(4321, 0), (4321, 0), (4321, signal.SIGTERM)]
    assert "WATCHDOG: final infrastructure error for candidate-2 after 3 runs: new outage" in capsys.readouterr().out


def test_watch_budget_counts_all_records_for_acknowledged_instances(tmp_path, capsys):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1/final_infra_error.json",
        {"instance_id": "candidate-1", "runs": 3, "reason": "old"},
    )
    for instance_id, filename, dollars in [
        ("candidate-1", "record.json", 0.30),
        ("candidate-1", "record.infra-1.json", 0.20),
        ("candidate-1", "record.interrupted-1.json", 0.25),
        ("candidate-2", "record.json", 0.50),
    ]:
        _write_json(
            tmp_path / instance_id / filename,
            _record(instance_id, "infra_error", model_dollars=dollars),
        )
    signals = []
    assert watch.watch_pilot(
        tmp_path, 4321, model_budget_usd=1.0,
        kill=lambda pid, sig: signals.append((pid, sig)),
        sleep=lambda _: pytest.fail("over-budget watch must not sleep"),
    ) == 0
    assert signals == [(4321, 0), (4321, signal.SIGTERM)]
    assert "WATCHDOG: model spend $1.25 exceeds budget $1.00" in capsys.readouterr().out


@pytest.mark.parametrize("stop_rule", ["gate_looser", "retry loop"])
def test_watch_keeps_other_stop_rules_for_acknowledged_instances(
    tmp_path, capsys, stop_rule,
):
    watch = _watch_module()
    _write_json(
        tmp_path / "candidate-1/final_infra_error.json",
        {"instance_id": "candidate-1", "runs": 3, "reason": "old"},
    )
    if stop_rule == "gate_looser":
        _write_json(
            tmp_path / "candidate-1/record.json",
            _record("candidate-1", "ran", agreement="gate_looser"),
        )
    else:
        for number in range(1, 5):
            _write_json(
                tmp_path / "candidate-1" / f"record.infra-{number}.json",
                _record("candidate-1", "infra_error"),
            )
    signals = []
    assert watch.watch_pilot(
        tmp_path, 4321, kill=lambda pid, sig: signals.append((pid, sig)),
        sleep=lambda _: pytest.fail("watch must stop before sleeping"),
    ) == 0
    assert signals == [(4321, 0), (4321, signal.SIGTERM)]
    assert f"WATCHDOG: {stop_rule}" in capsys.readouterr().out
