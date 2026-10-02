from __future__ import annotations

import importlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest


DAYTONA_KEY = "daytona-secret-value"
OPENAI_KEY = "token-factory-secret-value"
MODEL = "nvidia/nemotron-3-super-120b-a12b"
GB = 1024**3
NOW = datetime(2026, 10, 1, 18, 30, tzinfo=timezone.utc)
REQUIRED_PERMISSIONS = [
    "delete:sandboxes",
    "delete:snapshots",
    "write:sandboxes",
    "write:snapshots",
]
DEFAULT = object()


def _preflight_module():
    return importlib.import_module("receipts.preflight")


@pytest.fixture(autouse=True)
def _away_from_the_real_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may read the repository's .env, which holds real keys."""

    monkeypatch.chdir(tmp_path)


def _set_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAYTONA_API_KEY", DAYTONA_KEY)
    monkeypatch.setenv("DAYTONA_API_URL", "https://daytona.example/api")
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://models.example/v1/")
    monkeypatch.setenv("NEMOTRON_MODEL", MODEL)


def _http_client(
    *,
    permissions=DEFAULT,
    context_length=262_144,
    supported_features: list[str] | None = None,
    usage_status: int = 403,
    usage_body=DEFAULT,
    model_data=DEFAULT,
    pricing=DEFAULT,
) -> httpx.AsyncClient:
    key_permissions = REQUIRED_PERMISSIONS if permissions is DEFAULT else permissions
    features = supported_features if supported_features is not None else ["tools", "reasoning"]
    limits_body = (
        {"cpu": {"limit": 10}, "memoryGiB": 10}
        if usage_body is DEFAULT
        else usage_body
    )
    model_pricing = (
        {"prompt": "0.0000001", "completion": "0.0000005"}
        if pricing is DEFAULT
        else pricing
    )
    models = (
        [
            {
                "id": MODEL,
                "context_length": context_length,
                "pricing": model_pricing,
                "per_request_limits": {"max_output_tokens": 32_768},
                "supported_features": features,
            }
        ]
        if model_data is DEFAULT
        else model_data
    )

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/api-keys/current":
            return httpx.Response(
                200,
                json={
                    "name": "harbor",
                    "createdAt": "2026-10-01T00:00:00Z",
                    "organizationId": "org-123",
                    "permissions": key_permissions,
                },
            )
        if request.url.path == "/api/organizations/org-123/usage":
            if usage_status == 200:
                return httpx.Response(200, json=limits_body)
            return httpx.Response(usage_status)
        if request.url.path == "/v1/models":
            if isinstance(context_length, float) and not math.isfinite(context_length):
                return httpx.Response(
                    200,
                    content=json.dumps({"data": models}, allow_nan=True),
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(200, json={"data": models})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def _snapshots(_api_key: str):
    return [
        SimpleNamespace(name="receipts-alpha", organization_id="org-123", size=2.5),
        SimpleNamespace(name="receipts-beta", organization_id="org-123", size=1.0),
        SimpleNamespace(name="spike-old", organization_id="org-123", size=0.5),
        SimpleNamespace(name="other-org", organization_id="org-999", size=99.0),
    ]


def _disk_with_free_gb(free_gb: float):
    return lambda _path: SimpleNamespace(total=100 * GB, used=(100 - free_gb) * GB, free=free_gb * GB)


async def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    out: Path | None = None,
    permissions=DEFAULT,
    context_length=262_144,
    supported_features: list[str] | None = None,
    usage_status: int = 403,
    free_gb: float = 40,
) -> int:
    module = _preflight_module()
    _set_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pilot").mkdir(exist_ok=True)
    async with _http_client(
        permissions=permissions,
        context_length=context_length,
        supported_features=supported_features,
        usage_status=usage_status,
    ) as client:
        return await module.run_preflight(
            out=out,
            http_client=client,
            snapshot_lister=_snapshots,
            disk_usage=_disk_with_free_gb(free_gb),
            repo_root=tmp_path,
            now=lambda: NOW,
        )


@pytest.mark.asyncio
async def test_all_checks_pass_and_write_default_dated_json_without_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    status = await _run(tmp_path, monkeypatch)

    output_path = tmp_path / "pilot" / "preflight-2026-10-01.json"
    serialized = output_path.read_text(encoding="utf-8")
    report = json.loads(serialized)
    output = capsys.readouterr().out

    assert status == 0
    assert report["created_at"] == "2026-10-01T18:30:00Z"
    assert report["passed"] is True
    assert report["failures"] == []
    assert set(report["checks"]) == {
        "daytona_key",
        "daytona_snapshots",
        "daytona_organization_limits",
        "token_factory_model",
        "disk",
        "token_factory_balance",
    }
    assert report["checks"]["daytona_key"]["organization_id"] == "org-123"
    assert report["checks"]["daytona_key"]["key_name"] == "harbor"
    assert report["checks"]["daytona_key"]["missing_permissions"] == []
    assert report["checks"]["daytona_snapshots"]["count"] == 3
    assert report["checks"]["daytona_snapshots"]["total_size_gb"] == 4.0
    assert report["checks"]["daytona_snapshots"]["by_name_prefix"] == {
        "receipts": {"count": 2, "size_gb": 3.5},
        "spike": {"count": 1, "size_gb": 0.5},
    }
    assert report["checks"]["token_factory_model"]["context_length"] == 262_144
    assert report["checks"]["token_factory_model"]["supported_features"] == [
        "tools",
        "reasoning",
    ]
    assert report["checks"]["disk"]["free_gb"] == 40.0
    assert report["checks"]["token_factory_balance"] == {
        "available": False,
        "note": "check the Token Factory console before launch",
        "passed": True,
        "reason": "informational check",
    }
    assert DAYTONA_KEY not in serialized
    assert OPENAI_KEY not in serialized
    assert DAYTONA_KEY not in output
    assert OPENAI_KEY not in output


@pytest.mark.asyncio
async def test_missing_delete_snapshots_permission_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output_path = tmp_path / "preflight.json"
    permissions = [permission for permission in REQUIRED_PERMISSIONS if permission != "delete:snapshots"]

    status = await _run(
        tmp_path,
        monkeypatch,
        out=output_path,
        permissions=permissions,
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert status == 1
    assert report["passed"] is False
    assert "delete:snapshots" in report["failures"]
    assert report["checks"]["daytona_key"]["passed"] is False
    assert report["checks"]["daytona_key"]["missing_permissions"] == ["delete:snapshots"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context_length", "supported_features", "failure"),
    [
        (131_072, ["tools", "reasoning"], "token_factory_model.context_length"),
        (262_144, ["reasoning"], "token_factory_model.tools"),
    ],
)
async def test_model_must_have_context_headroom_and_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    context_length: int,
    supported_features: list[str],
    failure: str,
):
    output_path = tmp_path / "preflight.json"

    status = await _run(
        tmp_path,
        monkeypatch,
        out=output_path,
        context_length=context_length,
        supported_features=supported_features,
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert status == 1
    assert failure in report["failures"]
    assert report["checks"]["token_factory_model"]["passed"] is False


@pytest.mark.asyncio
async def test_organization_usage_403_is_unavailable_but_informational(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output_path = tmp_path / "preflight.json"

    status = await _run(
        tmp_path,
        monkeypatch,
        out=output_path,
        usage_status=403,
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    check = report["checks"]["daytona_organization_limits"]
    assert status == 0
    assert check["available"] is False
    assert check["status"] == 403
    assert check["passed"] is True


@pytest.mark.asyncio
async def test_disk_below_30_gb_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output_path = tmp_path / "preflight.json"

    status = await _run(
        tmp_path,
        monkeypatch,
        out=output_path,
        free_gb=29.9,
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert status == 1
    assert "disk" in report["failures"]
    assert report["checks"]["disk"]["passed"] is False
    assert report["checks"]["disk"]["free_gb"] == 29.9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client_options", "failed_check"),
    [
        ({"permissions": None}, "daytona_key"),
        ({"model_data": None}, "token_factory_model"),
    ],
)
async def test_null_response_collections_write_a_failed_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client_options: dict,
    failed_check: str,
):
    module = _preflight_module()
    _set_environment(monkeypatch)
    output_path = tmp_path / "preflight.json"

    async with _http_client(**client_options) as client:
        status = await module.run_preflight(
            out=output_path,
            http_client=client,
            snapshot_lister=_snapshots,
            disk_usage=_disk_with_free_gb(40),
            repo_root=tmp_path,
            now=lambda: NOW,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert status == 1
    assert report["checks"][failed_check]["passed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("context_length", [float("nan"), float("inf")])
async def test_nonfinite_model_context_fails_and_writes_standard_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    context_length: float,
):
    output_path = tmp_path / "preflight.json"

    status = await _run(
        tmp_path,
        monkeypatch,
        out=output_path,
        context_length=context_length,
    )

    serialized = output_path.read_text(encoding="utf-8")
    report = json.loads(serialized)
    assert status == 1
    assert report["checks"]["token_factory_model"]["context_length"] is None
    assert "NaN" not in serialized
    assert "Infinity" not in serialized


@pytest.mark.asyncio
async def test_reflected_keys_are_redacted_from_nested_raw_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _preflight_module()
    _set_environment(monkeypatch)
    output_path = tmp_path / "preflight.json"
    usage_body = {
        "echo": DAYTONA_KEY,
        f"field-{DAYTONA_KEY}": {"nested": f"before-{OPENAI_KEY}-after"},
    }

    async with _http_client(
        usage_status=200,
        usage_body=usage_body,
        pricing={"source": OPENAI_KEY},
    ) as client:
        status = await module.run_preflight(
            out=output_path,
            http_client=client,
            snapshot_lister=_snapshots,
            disk_usage=_disk_with_free_gb(40),
            repo_root=tmp_path,
            now=lambda: NOW,
        )

    serialized = output_path.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert status == 0
    assert DAYTONA_KEY not in serialized
    assert OPENAI_KEY not in serialized
    assert DAYTONA_KEY not in output
    assert OPENAI_KEY not in output
    assert "[REDACTED]" in serialized


@pytest.mark.asyncio
async def test_snapshot_sdk_lister_fetches_every_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _preflight_module()
    _set_environment(monkeypatch)
    output_path = tmp_path / "preflight.json"

    class FakeSnapshotService:
        async def list(self, page=None):
            page_number = 1 if page is None else page
            items = {
                1: [SimpleNamespace(name="receipts-one", organization_id="org-123", size=1.0)],
                2: [
                    SimpleNamespace(name="receipts-two", organization_id="org-123", size=2.0),
                    SimpleNamespace(name="other", organization_id="org-999", size=50.0),
                ],
            }[page_number]
            return SimpleNamespace(items=items, page=page_number, total_pages=2)

    class FakeAsyncDaytona:
        def __init__(self, _config):
            self.snapshot = FakeSnapshotService()

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return None

    monkeypatch.setattr(module, "AsyncDaytona", FakeAsyncDaytona)
    async with _http_client() as client:
        status = await module.run_preflight(
            out=output_path,
            http_client=client,
            disk_usage=_disk_with_free_gb(40),
            repo_root=tmp_path,
            now=lambda: NOW,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    snapshots = report["checks"]["daytona_snapshots"]
    assert status == 0
    assert snapshots["count"] == 2
    assert snapshots["total_size_gb"] == 3.0


@pytest.mark.asyncio
async def test_disk_compares_unrounded_free_bytes_to_30_gb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _preflight_module()
    _set_environment(monkeypatch)
    output_path = tmp_path / "preflight.json"

    async with _http_client() as client:
        status = await module.run_preflight(
            out=output_path,
            http_client=client,
            snapshot_lister=_snapshots,
            disk_usage=lambda _path: SimpleNamespace(free=30 * GB - 1),
            repo_root=tmp_path,
            now=lambda: NOW,
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert status == 1
    assert report["checks"]["disk"]["passed"] is False


def test_token_factory_settings_follow_the_model_client_precedence(tmp_path):
    """The model client lets .env override the shell, so a shell OPENAI_API_KEY for
    another provider must not reach Token Factory; Daytona keeps the shell first."""

    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "OPENAI_API_KEY=tf-key-from-dotenv\n"
        "OPENAI_BASE_URL=https://tf.example/v1/\n"
        "DAYTONA_API_KEY=daytona-from-dotenv\n",
        encoding="utf-8",
    )

    config = _preflight_module().load_preflight_config(
        environ={
            "OPENAI_API_KEY": "another-provider-key",
            "DAYTONA_API_KEY": "daytona-from-shell",
        },
        dotenv_path=dotenv,
    )

    assert config.openai_api_key == "tf-key-from-dotenv"
    assert config.openai_base_url == "https://tf.example/v1/"
    assert config.daytona_api_key == "daytona-from-shell"
