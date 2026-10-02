"""Read-only launch preflight checks with a dated JSON artifact."""

from __future__ import annotations

import json
import math
import os
import shutil
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
from daytona import AsyncDaytona, DaytonaConfig
from dotenv import dotenv_values

from receipts.llm import _settings as _model_client_settings


DEFAULT_DAYTONA_API_URL = "https://app.daytona.io/api"
DEFAULT_OPENAI_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
MINIMUM_CONTEXT_LENGTH = 200_000
MINIMUM_FREE_GB = 30
REQUIRED_DAYTONA_PERMISSIONS = frozenset(
    {
        "write:sandboxes",
        "delete:sandboxes",
        "write:snapshots",
        "delete:snapshots",
    }
)


class _DiskUsage(Protocol):
    free: int | float


SnapshotLister = Callable[[str], Awaitable[Sequence[Any]]]
DiskUsage = Callable[[Path], _DiskUsage]
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class PreflightConfig:
    daytona_api_key: str | None = field(repr=False)
    daytona_api_url: str
    openai_api_key: str | None = field(repr=False)
    openai_base_url: str
    model: str


def _value(
    name: str,
    *,
    environ: Mapping[str, str],
    dotenv: Mapping[str, str | None],
    default: str | None = None,
) -> str | None:
    value = environ.get(name) or dotenv.get(name) or default
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def load_preflight_config(
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path = Path(".env"),
) -> PreflightConfig:
    """Load each setting the way the component that uses it does.

    Daytona settings come from the environment first, then ``.env``, as the
    executor reads them. Token Factory settings use the model client's rule,
    where ``.env`` overrides the environment, so a shell ``OPENAI_API_KEY``
    for another provider is never sent to Token Factory.
    """

    process_environment = os.environ if environ is None else environ
    file_environment = dotenv_values(dotenv_path)
    model_settings = _model_client_settings(Path(dotenv_path), environ)
    return PreflightConfig(
        daytona_api_key=_value(
            "DAYTONA_API_KEY",
            environ=process_environment,
            dotenv=file_environment,
        ),
        daytona_api_url=_value(
            "DAYTONA_API_URL",
            environ=process_environment,
            dotenv=file_environment,
            default=DEFAULT_DAYTONA_API_URL,
        )
        or DEFAULT_DAYTONA_API_URL,
        openai_api_key=_value(
            "OPENAI_API_KEY",
            environ=model_settings,
            dotenv={},
        ),
        openai_base_url=_value(
            "OPENAI_BASE_URL",
            environ=model_settings,
            dotenv={},
            default=DEFAULT_OPENAI_BASE_URL,
        )
        or DEFAULT_OPENAI_BASE_URL,
        model=_value(
            "NEMOTRON_MODEL",
            environ=model_settings,
            dotenv={},
            default=DEFAULT_MODEL,
        )
        or DEFAULT_MODEL,
    )


async def _list_daytona_snapshots(api_key: str) -> Sequence[Any]:
    async with AsyncDaytona(DaytonaConfig(api_key=api_key)) as daytona:
        page = await daytona.snapshot.list()
        items = list(getattr(page, "items", page))
        current_page = getattr(page, "page", 1)
        total_pages = getattr(page, "total_pages", 1)
        if not isinstance(current_page, int) or current_page < 1:
            current_page = 1
        if isinstance(total_pages, int):
            for page_number in range(current_page + 1, total_pages + 1):
                next_page = await daytona.snapshot.list(page=page_number)
                items.extend(getattr(next_page, "items", next_page))
        return items


def _exception_name(exc: Exception) -> str:
    """Return useful failure context without risking secret-bearing messages."""

    return type(exc).__name__


async def _daytona_key_check(
    client: httpx.AsyncClient,
    config: PreflightConfig,
    failures: list[str],
) -> tuple[dict[str, Any], str | None]:
    facts: dict[str, Any] = {
        "status": None,
        "organization_id": None,
        "key_name": None,
        "created_at": None,
        "permissions": [],
        "missing_permissions": sorted(REQUIRED_DAYTONA_PERMISSIONS),
    }
    if config.daytona_api_key is None:
        facts.update(passed=False, reason="DAYTONA_API_KEY is not configured")
        failures.append("DAYTONA_API_KEY")
        return facts, None

    try:
        response = await client.get(
            f"{config.daytona_api_url.rstrip('/')}/api-keys/current",
            headers={"Authorization": f"Bearer {config.daytona_api_key}"},
        )
    except Exception as exc:
        facts.update(
            passed=False,
            reason=f"Daytona key lookup failed ({_exception_name(exc)})",
        )
        failures.append("daytona_key")
        return facts, None

    facts["status"] = response.status_code
    if response.status_code != 200:
        facts.update(
            passed=False,
            reason=f"Daytona key lookup returned status {response.status_code}",
        )
        failures.append("daytona_key")
        return facts, None

    try:
        body = response.json()
    except ValueError:
        facts.update(passed=False, reason="Daytona key lookup returned invalid JSON")
        failures.append("daytona_key")
        return facts, None

    if not isinstance(body, dict):
        facts.update(passed=False, reason="Daytona key lookup returned an invalid object")
        failures.append("daytona_key")
        return facts, None

    raw_permissions = body.get("permissions")
    permissions = (
        sorted(
            permission
            for permission in raw_permissions
            if isinstance(permission, str)
        )
        if isinstance(raw_permissions, list)
        else []
    )
    missing = sorted(REQUIRED_DAYTONA_PERMISSIONS - set(permissions))
    organization_id = body.get("organizationId")
    facts.update(
        organization_id=organization_id if isinstance(organization_id, str) else None,
        key_name=body.get("name") if isinstance(body.get("name"), str) else None,
        created_at=(
            body.get("createdAt") if isinstance(body.get("createdAt"), str) else None
        ),
        permissions=permissions,
        missing_permissions=missing,
    )
    if not isinstance(raw_permissions, list):
        facts.update(passed=False, reason="Daytona key response has invalid permissions")
        failures.extend(missing)
    elif not facts["organization_id"]:
        facts.update(passed=False, reason="Daytona key response has no organization id")
        failures.append("daytona_key.organization_id")
    elif missing:
        facts.update(
            passed=False,
            reason="missing required permissions: " + ", ".join(missing),
        )
        failures.extend(missing)
    else:
        facts.update(passed=True, reason="required permissions are present")
    return facts, facts["organization_id"]


async def _daytona_snapshots_check(
    config: PreflightConfig,
    organization_id: str | None,
    snapshot_lister: SnapshotLister,
) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "available": False,
        "count": 0,
        "total_size_gb": 0.0,
        "by_name_prefix": {},
        "passed": True,
        "reason": "informational check",
    }
    if config.daytona_api_key is None or organization_id is None:
        facts["reason"] = "informational check unavailable without a verified Daytona key"
        return facts

    try:
        snapshots = await snapshot_lister(config.daytona_api_key)
        own = [
            snapshot
            for snapshot in snapshots
            if getattr(snapshot, "organization_id", None) == organization_id
        ]
        grouped: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {"count": 0, "size_gb": 0.0}
        )
        total_size = 0.0
        for snapshot in own:
            name = str(getattr(snapshot, "name", ""))
            prefix = name.split("-", maxsplit=1)[0]
            size = float(getattr(snapshot, "size", 0) or 0)
            grouped[prefix]["count"] += 1
            grouped[prefix]["size_gb"] += size
            total_size += size
        facts.update(
            available=True,
            count=len(own),
            total_size_gb=round(total_size, 3),
            by_name_prefix={
                prefix: {
                    "count": values["count"],
                    "size_gb": round(float(values["size_gb"]), 3),
                }
                for prefix, values in sorted(grouped.items())
            },
        )
    except Exception as exc:
        facts["reason"] = f"informational check unavailable ({_exception_name(exc)})"
    return facts


async def _daytona_limits_check(
    client: httpx.AsyncClient,
    config: PreflightConfig,
    organization_id: str | None,
) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "available": False,
        "status": None,
        "passed": True,
        "reason": "informational check",
    }
    if config.daytona_api_key is None or organization_id is None:
        facts["reason"] = "informational check unavailable without a verified Daytona key"
        return facts

    try:
        response = await client.get(
            f"{config.daytona_api_url.rstrip('/')}/organizations/{organization_id}/usage",
            headers={"Authorization": f"Bearer {config.daytona_api_key}"},
        )
    except Exception as exc:
        facts["reason"] = f"informational check unavailable ({_exception_name(exc)})"
        return facts

    facts["status"] = response.status_code
    if response.status_code != 200:
        return facts
    try:
        body = response.json()
    except ValueError:
        facts["reason"] = "informational check returned invalid JSON"
        return facts
    facts.update(available=True, usage=body)
    return facts


async def _token_factory_model_check(
    client: httpx.AsyncClient,
    config: PreflightConfig,
    failures: list[str],
) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "status": None,
        "model_id": config.model,
        "listed": False,
        "context_length": None,
        "pricing": None,
        "per_request_limits": None,
        "supported_features": [],
    }
    if config.openai_api_key is None:
        facts.update(passed=False, reason="OPENAI_API_KEY is not configured")
        failures.append("OPENAI_API_KEY")
        return facts

    try:
        response = await client.get(
            f"{config.openai_base_url.rstrip('/')}/models",
            params={"verbose": "true"},
            headers={"Authorization": f"Bearer {config.openai_api_key}"},
        )
    except Exception as exc:
        facts.update(
            passed=False,
            reason=f"Token Factory model lookup failed ({_exception_name(exc)})",
        )
        failures.append("token_factory_model")
        return facts

    facts["status"] = response.status_code
    if response.status_code != 200:
        facts.update(
            passed=False,
            reason=f"Token Factory model lookup returned status {response.status_code}",
        )
        failures.append("token_factory_model")
        return facts

    try:
        body = response.json()
    except ValueError:
        facts.update(passed=False, reason="Token Factory model lookup returned invalid JSON")
        failures.append("token_factory_model")
        return facts

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        facts.update(passed=False, reason="Token Factory model list is invalid")
        failures.append("token_factory_model")
        return facts
    model = next(
        (
            item
            for item in data
            if isinstance(item, dict) and item.get("id") == config.model
        ),
        None,
    )
    if model is None:
        facts.update(passed=False, reason="configured model is not listed")
        failures.append("token_factory_model.listed")
        return facts

    context_length = model.get("context_length")
    if type(context_length) is not int:
        context_length = None
    features = model.get("supported_features")
    supported_features = (
        [feature for feature in features if isinstance(feature, str)]
        if isinstance(features, list)
        else []
    )
    facts.update(
        listed=True,
        context_length=context_length,
        pricing=model.get("pricing"),
        per_request_limits=model.get("per_request_limits"),
        supported_features=supported_features,
    )

    reasons = []
    if "tools" not in supported_features:
        failures.append("token_factory_model.tools")
        reasons.append("tools are not supported")
    if context_length is None or context_length < MINIMUM_CONTEXT_LENGTH:
        failures.append("token_factory_model.context_length")
        reasons.append(f"context length is below {MINIMUM_CONTEXT_LENGTH}")
    facts.update(
        passed=not reasons,
        reason="model meets launch requirements" if not reasons else "; ".join(reasons),
    )
    return facts


def _disk_check(
    repo_root: Path,
    disk_usage: DiskUsage,
    failures: list[str],
) -> dict[str, Any]:
    try:
        free_bytes = float(disk_usage(repo_root).free)
        free_gb = round(free_bytes / (1024**3), 3)
    except Exception as exc:
        failures.append("disk")
        return {
            "free_gb": None,
            "minimum_free_gb": MINIMUM_FREE_GB,
            "passed": False,
            "reason": f"disk usage lookup failed ({_exception_name(exc)})",
        }
    passed = (
        math.isfinite(free_bytes)
        and free_bytes >= MINIMUM_FREE_GB * (1024**3)
    )
    if not passed:
        failures.append("disk")
    return {
        "free_gb": free_gb,
        "minimum_free_gb": MINIMUM_FREE_GB,
        "passed": passed,
        "reason": (
            "enough free space"
            if passed
            else f"free space is below {MINIMUM_FREE_GB} GB"
        ),
    }


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_json_value(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, Mapping):
        return {
            _safe_json_value(key, secrets): _safe_json_value(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(item, secrets) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


async def _collect_preflight(
    *,
    client: httpx.AsyncClient,
    config: PreflightConfig,
    snapshot_lister: SnapshotLister,
    disk_usage: DiskUsage,
    repo_root: Path,
    created_at: datetime,
) -> dict[str, Any]:
    failures: list[str] = []
    key_check, organization_id = await _daytona_key_check(client, config, failures)
    snapshots_check = await _daytona_snapshots_check(
        config,
        organization_id,
        snapshot_lister,
    )
    limits_check = await _daytona_limits_check(client, config, organization_id)
    model_check = await _token_factory_model_check(client, config, failures)
    disk_check = _disk_check(repo_root, disk_usage, failures)
    balance_check = {
        "available": False,
        "note": "check the Token Factory console before launch",
        "passed": True,
        "reason": "informational check",
    }
    return {
        "created_at": _utc_timestamp(created_at),
        "checks": {
            "daytona_key": key_check,
            "daytona_snapshots": snapshots_check,
            "daytona_organization_limits": limits_check,
            "token_factory_model": model_check,
            "disk": disk_check,
            "token_factory_balance": balance_check,
        },
        "passed": not failures,
        "failures": failures,
    }


async def run_preflight(
    out: Path | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
    snapshot_lister: SnapshotLister = _list_daytona_snapshots,
    disk_usage: DiskUsage = shutil.disk_usage,
    repo_root: Path | None = None,
    now: Clock = lambda: datetime.now(timezone.utc),
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path = Path(".env"),
) -> int:
    """Run the preflight, write its JSON artifact, and return its exit code."""

    created_at = now()
    output_path = out or Path("pilot") / f"preflight-{created_at.astimezone(timezone.utc):%Y-%m-%d}.json"
    config = load_preflight_config(environ=environ, dotenv_path=dotenv_path)
    root = Path.cwd() if repo_root is None else repo_root

    if http_client is None:
        async with httpx.AsyncClient(timeout=20) as owned_client:
            report = await _collect_preflight(
                client=owned_client,
                config=config,
                snapshot_lister=snapshot_lister,
                disk_usage=disk_usage,
                repo_root=root,
                created_at=created_at,
            )
    else:
        report = await _collect_preflight(
            client=http_client,
            config=config,
            snapshot_lister=snapshot_lister,
            disk_usage=disk_usage,
            repo_root=root,
            created_at=created_at,
        )

    secrets = tuple(
        secret
        for secret in (config.daytona_api_key, config.openai_api_key)
        if secret
    )
    safe_report = _safe_json_value(report, secrets)
    output_path.write_text(
        json.dumps(safe_report, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = "PASS" if safe_report["passed"] else "FAIL"
    print(f"PREFLIGHT {result} {output_path}")
    return 0 if safe_report["passed"] else 1
