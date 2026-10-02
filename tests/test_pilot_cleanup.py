from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


def _cleanup_module():
    try:
        return importlib.import_module("receipts.pilot.cleanup")
    except ModuleNotFoundError:
        pytest.fail("receipts.pilot.cleanup is missing")


def _write_manifest(path: Path) -> bytes:
    entries = [
        {
            "id": "snapshot-pending",
            "name": "receipts-pending",
            "created_at": "2026-10-02T12:00:00+00:00",
            "status": "delete_failed",
            "error": "denied for secret-daytona-key",
        },
        {
            "id": "snapshot-deleted",
            "name": "receipts-deleted",
            "created_at": "2026-10-02T12:01:00+00:00",
            "status": "deleted",
            "error": None,
        },
    ]
    path.parent.mkdir(parents=True)
    content = (json.dumps(entries, indent=2) + "\n").encode()
    path.write_bytes(content)
    return content


async def test_cleanup_dry_run_lists_pending_entries_without_changing_manifest(
    tmp_path: Path,
):
    cleanup = _cleanup_module()
    manifest = tmp_path / "pilot" / "task" / "cleanup.json"
    original = _write_manifest(manifest)

    result = await cleanup.cleanup_manifests(
        tmp_path,
        api=None,
        yes=False,
        secrets=("secret-daytona-key",),
    )
    rendered = cleanup.render_cleanup(result)

    assert manifest.read_bytes() == original
    assert "snapshot-pending" in rendered
    assert "receipts-pending" in rendered
    assert "snapshot-deleted" not in rendered
    assert "secret-daytona-key" not in rendered
    assert "denied for [REDACTED]" in rendered
    assert "manifests=1 pending=1 deleted=0 failed=0 dry_run=true" in rendered


async def test_cleanup_yes_deletes_treats_404_as_deleted_and_records_403(
    tmp_path: Path,
):
    cleanup = _cleanup_module()
    manifest = tmp_path / "cleanup.json"
    entries = [
        {
            "id": snapshot_id,
            "name": f"receipts-{snapshot_id}",
            "created_at": "2026-10-02T12:00:00+00:00",
            "status": "created",
            "error": None,
        }
        for snapshot_id in ("ok", "gone", "denied")
    ]
    manifest.write_text(json.dumps(entries) + "\n", encoding="utf-8")

    class FakeApi:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def delete_snapshot(self, snapshot: str, *, timeout_s: int) -> None:
            assert timeout_s == 120
            self.calls.append(snapshot)
            if snapshot == "gone":
                error = RuntimeError("not found")
                error.status_code = 404
                raise error
            if snapshot == "denied":
                error = RuntimeError("denied for secret-daytona-key")
                error.status_code = 403
                raise error

    api = FakeApi()
    result = await cleanup.cleanup_manifests(
        tmp_path,
        api=api,
        yes=True,
        secrets=("secret-daytona-key",),
    )
    rendered = cleanup.render_cleanup(result)
    updated = json.loads(manifest.read_text(encoding="utf-8"))

    assert api.calls == ["ok", "gone", "denied"]
    assert [entry["status"] for entry in updated] == [
        "deleted",
        "deleted",
        "delete_failed",
    ]
    assert updated[0]["error"] is None
    assert updated[1]["error"] is None
    assert updated[2]["error"] == "denied for [REDACTED]"
    assert "manifests=1 pending=3 deleted=2 failed=1 dry_run=false" in rendered
    assert "secret-daytona-key" not in rendered


def test_cleanup_cli_prefers_environment_key_and_never_prints_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    import receipts.cli as cli

    manifest = tmp_path / "cleanup.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "id": "denied",
                    "name": "receipts-denied",
                    "created_at": "2026-10-02T12:00:00+00:00",
                    "status": "created",
                    "error": None,
                },
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "DAYTONA_API_KEY=dotenv-daytona-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DAYTONA_API_KEY", "environment-daytona-key")
    captured: dict[str, str] = {}

    class FakeApi:
        closed = False

        async def delete_snapshot(self, snapshot: str, *, timeout_s: int) -> None:
            error = RuntimeError("denied for environment-daytona-key")
            error.status_code = 403
            raise error

        async def close(self) -> None:
            self.closed = True

    api = FakeApi()

    def fake_config(*, api_key: str):
        captured["api_key"] = api_key
        return object()

    monkeypatch.setattr(cli, "DaytonaConfig", fake_config)
    monkeypatch.setattr(cli, "AsyncDaytona", lambda config: config)
    monkeypatch.setattr(cli, "AsyncDaytonaApi", lambda client: api)

    status = cli.main(["pilot", "cleanup", "--root", str(tmp_path), "--yes"])

    output = capsys.readouterr().out
    assert status == 1
    assert captured["api_key"] == "environment-daytona-key"
    assert api.closed is True
    assert "environment-daytona-key" not in output
    assert "dotenv-daytona-key" not in output
    assert "denied for [REDACTED]" in output
