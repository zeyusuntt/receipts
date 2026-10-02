"""Async Token Factory Sandboxes REST client and deterministic in-memory fake."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import uuid as uuid_module
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, TypeAlias
from urllib.parse import urljoin, urlparse

import httpx

from receipts.llm import _settings


DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/sandboxes"
_MAX_ATTEMPTS = 5
_TERMINAL_STATUSES = frozenset({"SUCCESS", "FAILED", "CANCELLED"})


@dataclass(frozen=True)
class StreamDescription:
    value: str
    encoding: str = "base64"
    truncated: bool = False


@dataclass(frozen=True)
class InstanceFileSpec:
    uuid: str
    mode: str
    uid: int = 0
    gid: int = 0


@dataclass(frozen=True)
class UploadedFile:
    """An uploaded file. Spawn requests reference it by uuid in their files map."""

    uuid: str
    sha256: str


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None
    stdout: str
    stderr: str
    image_uuid: str | None
    duration_s: float
    cost: float
    status: str
    error: str | None
    retries: dict[str, int] = field(default_factory=dict)


class TokenFactoryApiError(RuntimeError):
    """A sanitized non-success response from the sandbox API."""

    def __init__(
        self,
        status_code: int,
        method: str,
        path: str,
        detail: str,
    ) -> None:
        self.status_code = status_code
        self.method = method
        self.path = path
        self.detail = detail
        super().__init__(f"Token Factory sandbox API {method} {path} returned {status_code}: {detail}")


FileSpecValue: TypeAlias = InstanceFileSpec | Mapping[str, Any]
StreamValue: TypeAlias = StreamDescription | Mapping[str, Any] | str | bytes | None
FakeTree: TypeAlias = dict[str, bytes]
FakeHandlerResult: TypeAlias = tuple[int, str, str, FakeTree]
FakeHandler: TypeAlias = Callable[
    [FakeTree],
    FakeHandlerResult | Awaitable[FakeHandlerResult],
]


def _stream_payload(value: StreamValue) -> dict[str, Any]:
    if value is None:
        return {"value": "", "encoding": "ascii", "truncated": False}
    if isinstance(value, StreamDescription):
        return asdict(value)
    if isinstance(value, bytes):
        return {
            "value": base64.b64encode(value).decode("ascii"),
            "encoding": "base64",
            "truncated": False,
        }
    if isinstance(value, str):
        return {"value": value, "encoding": "ascii", "truncated": False}
    return {
        "value": str(value.get("value", "")),
        "encoding": str(value.get("encoding", "base64")),
        "truncated": bool(value.get("truncated", False)),
    }


def _file_payload(value: FileSpecValue) -> dict[str, Any]:
    if isinstance(value, InstanceFileSpec):
        return asdict(value)
    return {
        "uuid": str(value["uuid"]),
        "mode": str(value["mode"]),
        "uid": int(value.get("uid", 0)),
        "gid": int(value.get("gid", 0)),
    }


def _decode_stream(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    raw = str(value.get("value", ""))
    encoding = str(value.get("encoding", "base64")).lower()
    if encoding == "ascii":
        return raw
    if encoding == "base64":
        return base64.b64decode(raw).decode(errors="replace")
    return raw.encode("latin-1", errors="replace").decode(errors="replace")


def _run_result(operation: Mapping[str, Any], retries: Mapping[str, int]) -> RunResult:
    metadata = operation.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    process = metadata.get("result")
    process = process if isinstance(process, Mapping) else {}
    state = process.get("state")
    state = state if isinstance(state, Mapping) else {}
    resources = process.get("resources")
    resources = resources if isinstance(resources, Mapping) else {}
    image_result = operation.get("result")
    image_result = image_result if isinstance(image_result, Mapping) else {}

    raw_exit_code = state.get("exit_code")
    exit_code = int(raw_exit_code) if raw_exit_code is not None else None
    duration = resources.get("elapsed_time", operation.get("duration", 0.0))
    cost = resources.get("cost", 0.0)
    raw_error = operation.get("error")
    raw_image = image_result.get("image")
    return RunResult(
        exit_code=exit_code,
        stdout=_decode_stream(process.get("stdout")),
        stderr=_decode_stream(process.get("stderr")),
        image_uuid=str(raw_image) if raw_image is not None else None,
        duration_s=float(duration or 0.0),
        cost=float(cost or 0.0),
        status=str(operation.get("status", "")),
        error=str(raw_error) if raw_error is not None else None,
        retries=dict(sorted(retries.items())),
    )


class TokenFactorySandboxApi:
    """A narrow async client for the Token Factory Sandboxes REST API."""

    def __init__(
        self,
        api_key: str,
        project_id: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for Token Factory sandboxes")
        if not project_id:
            raise ValueError("NEBIUS_AI_PROJECT or NEBIUS_PROJECT_ID is required")
        self._api_key = api_key
        self.project_id = project_id
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._sleep = sleep

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        dotenv_path: Path = Path(".env"),
    ) -> TokenFactorySandboxApi:
        values = _settings(Path(dotenv_path), environ)
        api_key = values.get("OPENAI_API_KEY", "")
        project_id = values.get("NEBIUS_AI_PROJECT") or values.get("NEBIUS_PROJECT_ID", "")
        return cls(api_key, project_id)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self.base_url!r}, "
            f"project_id={self.project_id!r})"
        )

    async def __aenter__(self) -> TokenFactorySandboxApi:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Project": self.project_id,
        }

    def _safe_detail(self, response: httpx.Response) -> str:
        detail = ""
        try:
            data = response.json()
        except (ValueError, UnicodeDecodeError):
            detail = response.text
        else:
            if isinstance(data, Mapping):
                candidate = data.get("detail", data.get("error", data))
                detail = str(candidate)
            else:
                detail = str(data)
        detail = detail.strip() or response.reason_phrase or "request failed"
        return detail.replace(self._api_key, "[redacted]")[:1000]

    def _error(self, response: httpx.Response) -> TokenFactoryApiError:
        request = response.request
        return TokenFactoryApiError(
            response.status_code,
            request.method,
            request.url.path,
            self._safe_detail(response),
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        retries: dict[str, int] | None = None,
        allowed_statuses: frozenset[int] = frozenset(),
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        retry_counts = retries if retries is not None else {}
        request_headers = self._headers()
        if headers:
            request_headers.update(headers)

        for attempt in range(_MAX_ATTEMPTS):
            response = await self._client.request(
                method,
                f"{self.base_url}{path}",
                headers=request_headers,
                follow_redirects=False,
                **kwargs,
            )
            retry_kind = None
            if response.status_code == 429:
                retry_kind = "429"
            elif 500 <= response.status_code <= 599:
                retry_kind = "5xx"

            if retry_kind is not None and attempt + 1 < _MAX_ATTEMPTS:
                retry_counts[retry_kind] = retry_counts.get(retry_kind, 0) + 1
                await self._sleep(float(2**attempt))
                continue
            if response.status_code >= 400 and response.status_code not in allowed_statuses:
                raise self._error(response)
            return response
        raise AssertionError("unreachable")

    async def whoami(self) -> dict[str, Any]:
        response = await self._request("GET", "/v1/whoami")
        return dict(response.json())

    async def image_by_tag(self, tag: str) -> str | None:
        response = await self._request(
            "GET",
            "/v1/inspect/",
            params={"tag": tag},
            allowed_statuses=frozenset({404}),
        )
        if response.status_code == 404:
            return None
        if response.status_code != 302:
            raise TokenFactoryApiError(
                response.status_code,
                response.request.method,
                response.request.url.path,
                "expected a 302 image redirect",
            )
        location = response.headers.get("Location")
        if not location:
            raise TokenFactoryApiError(
                response.status_code,
                response.request.method,
                response.request.url.path,
                "image redirect has no Location header",
            )
        resolved = urlparse(urljoin(str(response.request.url), location))
        inspect_path = response.request.url.path
        if not resolved.path.startswith(inspect_path):
            raise TokenFactoryApiError(
                response.status_code,
                response.request.method,
                response.request.url.path,
                "image redirect leaves the inspect endpoint",
            )
        relative = resolved.path[len(inspect_path) :].strip("/")
        if not relative or "/" in relative:
            raise TokenFactoryApiError(
                response.status_code,
                response.request.method,
                response.request.url.path,
                "image redirect does not contain one image uuid",
            )
        return relative

    async def image(self, image_uuid: str) -> dict[str, Any]:
        response = await self._request("GET", f"/v1/inspect/{image_uuid}/")
        return dict(response.json())

    async def list_files(self, image_uuid: str, path: str) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            f"/v1/inspect/{image_uuid}/list",
            params={"path": path},
        )
        return [dict(item) for item in response.json()["files"]]

    async def download(self, image_uuid: str, path: str) -> bytes | None:
        response = await self._request(
            "GET",
            f"/v1/inspect/{image_uuid}/download",
            params={"path": path},
            allowed_statuses=frozenset({404}),
        )
        return None if response.status_code == 404 else response.content

    async def upload(self, data: bytes) -> UploadedFile:
        digest = hashlib.sha256(data).hexdigest()
        existing = await self._request(
            "HEAD",
            f"/v1/files/{digest}",
            allowed_statuses=frozenset({404}),
        )
        if existing.status_code != 404:
            response = await self._request("GET", f"/v1/files/{digest}")
        else:
            response = await self._request(
                "POST",
                "/v1/files",
                content=data,
                headers={"Content-Type": "application/octet-stream"},
            )
        result = response.json()
        uploaded = UploadedFile(uuid=str(result["uuid"]), sha256=str(result.get("sha256", digest)))
        if uploaded.sha256 != digest:
            raise TokenFactoryApiError(
                response.status_code,
                response.request.method,
                response.request.url.path,
                "uploaded file sha256 does not match its content",
            )
        return uploaded

    @staticmethod
    def _spawn_body(
        *,
        command: str,
        image: str,
        hostname: str,
        args: list[str] | tuple[str, ...] | None,
        shell: bool,
        env: Mapping[str, str] | None,
        cwd: str,
        disposable: bool,
        stdin: StreamValue,
        timeout: int,
        truncate_output_at: int,
        files: Mapping[str, FileSpecValue] | None,
        preserve_env: bool,
    ) -> dict[str, Any]:
        if timeout > 3600:
            raise ValueError("Token Factory sandbox timeout cannot exceed 3600 seconds")
        file_payloads: dict[str, dict[str, Any]] = {}
        for path, spec in (files or {}).items():
            if not PurePosixPath(path).is_absolute():
                raise ValueError(f"sandbox file destination must be absolute: {path}")
            file_payloads[path] = _file_payload(spec)
        return {
            "command": command,
            "image": image,
            "hostname": hostname,
            "args": list(args or []),
            "shell": shell,
            "env": dict(env or {}),
            "cwd": cwd,
            "disposable": disposable,
            "stdin": _stream_payload(stdin),
            "timeout": timeout,
            "truncate_output_at": truncate_output_at,
            "files": file_payloads,
            "preserve_env": preserve_env,
        }

    async def _spawn(
        self,
        *,
        retries: dict[str, int],
        command: str,
        image: str,
        hostname: str,
        args: list[str] | tuple[str, ...] | None,
        shell: bool,
        env: Mapping[str, str] | None,
        cwd: str,
        disposable: bool,
        stdin: StreamValue,
        timeout: int,
        truncate_output_at: int,
        files: Mapping[str, FileSpecValue] | None,
        preserve_env: bool,
    ) -> str:
        response = await self._request(
            "POST",
            "/v1/instances",
            retries=retries,
            json=self._spawn_body(
                command=command,
                image=image,
                hostname=hostname,
                args=args,
                shell=shell,
                env=env,
                cwd=cwd,
                disposable=disposable,
                stdin=stdin,
                timeout=timeout,
                truncate_output_at=truncate_output_at,
                files=files,
                preserve_env=preserve_env,
            ),
        )
        return str(response.json()["uuid"])

    async def spawn(
        self,
        *,
        command: str,
        image: str,
        hostname: str,
        args: list[str] | tuple[str, ...] | None = None,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        cwd: str,
        disposable: bool = False,
        stdin: StreamValue = None,
        timeout: int = 60,
        truncate_output_at: int = 65535,
        files: Mapping[str, FileSpecValue] | None = None,
        preserve_env: bool = False,
    ) -> str:
        return await self._spawn(
            retries={},
            command=command,
            image=image,
            hostname=hostname,
            args=args,
            shell=shell,
            env=env,
            cwd=cwd,
            disposable=disposable,
            stdin=stdin,
            timeout=timeout,
            truncate_output_at=truncate_output_at,
            files=files,
            preserve_env=preserve_env,
        )

    async def _operation(
        self,
        operation_id: str,
        retries: dict[str, int],
    ) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"/v1/operations/{operation_id}",
            retries=retries,
        )
        return dict(response.json())

    async def operation(self, operation_id: str) -> dict[str, Any]:
        return await self._operation(operation_id, {})

    async def _cancel(self, operation_id: str, retries: dict[str, int]) -> None:
        await self._request(
            "DELETE",
            f"/v1/operations/{operation_id}",
            retries=retries,
        )

    async def cancel(self, operation_id: str) -> None:
        await self._cancel(operation_id, {})

    async def _poll(
        self,
        operation_id: str,
        retries: dict[str, int],
    ) -> dict[str, Any]:
        delay = 0.1
        while True:
            operation = await self._operation(operation_id, retries)
            if str(operation.get("status", "")).upper() in _TERMINAL_STATUSES:
                return operation
            await self._sleep(delay)
            delay = min(delay * 2, 10.0)

    async def run(
        self,
        *,
        command: str,
        image: str,
        hostname: str,
        args: list[str] | tuple[str, ...] | None = None,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        cwd: str,
        disposable: bool = False,
        stdin: StreamValue = None,
        timeout: int = 60,
        truncate_output_at: int = 65535,
        files: Mapping[str, FileSpecValue] | None = None,
        preserve_env: bool = False,
        client_timeout_s: float | None = None,
    ) -> RunResult:
        retries: dict[str, int] = {}
        operation_id = await self._spawn(
            retries=retries,
            command=command,
            image=image,
            hostname=hostname,
            args=args,
            shell=shell,
            env=env,
            cwd=cwd,
            disposable=disposable,
            stdin=stdin,
            timeout=timeout,
            truncate_output_at=truncate_output_at,
            files=files,
            preserve_env=preserve_env,
        )
        try:
            poll = self._poll(operation_id, retries)
            if client_timeout_s is None:
                operation = await poll
            else:
                operation = await asyncio.wait_for(poll, timeout=client_timeout_s)
        except (TimeoutError, httpx.TimeoutException) as exc:
            try:
                await self._cancel(operation_id, retries)
            except Exception as cancel_error:
                exc.add_note(f"operation cancellation failed: {type(cancel_error).__name__}")
            raise TimeoutError(
                f"Token Factory sandbox operation {operation_id} exceeded the client timeout"
            ) from exc
        return _run_result(operation, retries)


class FakeTokenFactorySandboxApi:
    """In-memory image-tree model with command-scripted run semantics."""

    def __init__(
        self,
        *,
        images: Mapping[str, Mapping[str, bytes]] | None = None,
        tags: Mapping[str, str] | None = None,
        handlers: Mapping[str, FakeHandler] | None = None,
    ) -> None:
        self.images: dict[str, FakeTree] = {
            image_uuid: {path: bytes(data) for path, data in tree.items()}
            for image_uuid, tree in (images or {}).items()
        }
        self.tags = dict(tags or {})
        self.handlers = dict(handlers or {})
        self.calls: list[dict[str, Any]] = []
        self._uploads: dict[str, bytes] = {}
        self._operations: dict[str, dict[str, Any]] = {}
        self._image_operations: dict[str, str | None] = {
            image_uuid: None for image_uuid in self.images
        }
        self._image_number = 0
        self._operation_number = 0

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(images={len(self.images)}, "
            f"handlers={sorted(self.handlers)!r})"
        )

    async def __aenter__(self) -> FakeTokenFactorySandboxApi:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self.calls.append({"method": "aclose"})

    async def whoami(self) -> dict[str, Any]:
        self.calls.append({"method": "whoami"})
        return {
            "permissions": {
                "import": True,
                "spawn": True,
                "spawn_disposable": True,
                "list": True,
                "cancel": True,
                "set_image_tag": True,
            },
            "limits": {"instance_max_timeout": 3600, "instance_max_concurrency": 50},
        }

    async def image_by_tag(self, tag: str) -> str | None:
        self.calls.append({"method": "image_by_tag", "tag": tag})
        return self.tags.get(tag)

    async def image(self, image_uuid: str) -> dict[str, Any]:
        self.calls.append({"method": "image", "image": image_uuid})
        if image_uuid not in self.images:
            raise KeyError(image_uuid)
        tag = next((tag for tag, value in self.tags.items() if value == image_uuid), None)
        return {
            "uuid": image_uuid,
            "tag": tag,
            "created_at": None,
            "operation_uuid": self._image_operations.get(image_uuid),
        }

    async def list_files(self, image_uuid: str, path: str) -> list[dict[str, Any]]:
        self.calls.append({"method": "list_files", "image": image_uuid, "path": path})
        tree = self.images[image_uuid]
        root = path.rstrip("/") or "/"
        prefix = root if root == "/" else root + "/"
        entries: dict[str, dict[str, Any]] = {}
        for candidate, contents in sorted(tree.items()):
            if not candidate.startswith(prefix):
                continue
            relative = candidate[len(prefix) :]
            if not relative:
                continue
            first, separator, _rest = relative.partition("/")
            entry_path = f"/{first}" if root == "/" else f"{root}/{first}"
            if separator:
                entries[entry_path] = self._file_item(entry_path, b"", is_dir=True)
            else:
                entries[entry_path] = self._file_item(entry_path, contents, is_dir=False)
        return list(entries.values())

    @staticmethod
    def _file_item(path: str, contents: bytes, *, is_dir: bool) -> dict[str, Any]:
        return {
            "size": 0 if is_dir else len(contents),
            "path": path,
            "uid": 0,
            "gid": 0,
            "mode": 0o755 if is_dir else 0o644,
            "mtime": 0,
            "nlink": 1,
            "symlink_to": "",
            "is_dir": is_dir,
            "is_regular": not is_dir,
            "is_socket": False,
            "is_fifo": False,
            "is_symlink": False,
            "owner": "root",
            "group": "root",
        }

    async def download(self, image_uuid: str | None, path: str) -> bytes | None:
        self.calls.append({"method": "download", "image": image_uuid, "path": path})
        if image_uuid is None:
            return None
        contents = self.images[image_uuid].get(path)
        return bytes(contents) if contents is not None else None

    async def upload(self, data: bytes) -> UploadedFile:
        digest = hashlib.sha256(data).hexdigest()
        self.calls.append({"method": "upload", "sha256": digest})
        self._uploads.setdefault(digest, bytes(data))
        # The fake names an uploaded file by its digest, so files maps can use either.
        return UploadedFile(uuid=digest, sha256=digest)

    async def _execute(
        self,
        *,
        command: str,
        image: str,
        hostname: str,
        args: list[str] | tuple[str, ...] | None,
        shell: bool,
        env: Mapping[str, str] | None,
        cwd: str,
        disposable: bool,
        stdin: StreamValue,
        timeout: int,
        truncate_output_at: int,
        files: Mapping[str, FileSpecValue] | None,
        preserve_env: bool,
    ) -> str:
        if image not in self.images:
            raise KeyError(image)
        if timeout > 3600:
            raise ValueError("Token Factory sandbox timeout cannot exceed 3600 seconds")
        handler = self.handlers.get(command)
        if handler is None:
            raise AssertionError(f"no scripted Token Factory handler for command: {command}")

        input_tree = deepcopy(self.images[image])
        file_payloads: dict[str, dict[str, Any]] = {}
        for path, spec in (files or {}).items():
            if not PurePosixPath(path).is_absolute():
                raise ValueError(f"sandbox file destination must be absolute: {path}")
            payload = _file_payload(spec)
            file_payloads[path] = payload
            input_tree[path] = bytes(self._uploads[payload["uuid"]])

        handled = handler(input_tree)
        if inspect.isawaitable(handled):
            handled = await handled
        exit_code, stdout, stderr, output_tree = handled
        output_tree = {path: bytes(data) for path, data in output_tree.items()}

        self._operation_number += 1
        operation_id = f"fake-operation-{self._operation_number}"
        output_uuid = None
        if not disposable:
            self._image_number += 1
            output_uuid = f"fake-image-{self._image_number}-{uuid_module.uuid4()}"
            self.images[output_uuid] = deepcopy(output_tree)
            self._image_operations[output_uuid] = operation_id

        self._operations[operation_id] = self._operation_payload(
            command=command,
            image=image,
            hostname=hostname,
            args=list(args or []),
            shell=shell,
            env=dict(env or {}),
            cwd=cwd,
            disposable=disposable,
            stdin=_stream_payload(stdin),
            timeout=timeout,
            truncate_output_at=truncate_output_at,
            files=file_payloads,
            preserve_env=preserve_env,
            exit_code=int(exit_code),
            stdout=str(stdout),
            stderr=str(stderr),
            output_uuid=output_uuid,
        )
        return operation_id

    @staticmethod
    def _operation_payload(
        *,
        command: str,
        image: str,
        hostname: str,
        args: list[str],
        shell: bool,
        env: dict[str, str],
        cwd: str,
        disposable: bool,
        stdin: dict[str, Any],
        timeout: int,
        truncate_output_at: int,
        files: dict[str, dict[str, Any]],
        preserve_env: bool,
        exit_code: int,
        stdout: str,
        stderr: str,
        output_uuid: str | None,
    ) -> dict[str, Any]:
        resources = {
            "block_input": 0,
            "block_output": 0,
            "cost": 0.0,
            "elapsed_time": 0.0,
            "involuntary_switches": 0,
            "max_rss": 0,
            "monotonic_time": 0.0,
            "page_faults": 0,
            "page_faults_io": 0,
            "shared_memory": 0,
            "signals": 0,
            "swaps": 0,
            "system_cpu_time": 0.0,
            "unshared_memory": 0,
            "user_cpu_time": 0.0,
            "voluntary_switches": 0,
        }
        state = {
            "continued": False,
            "core_dump": False,
            "exit_code": exit_code,
            "pid": 1,
            "signal": 0,
            "stopped": False,
            "timed_out": False,
        }
        return {
            "kind": "instance",
            "status": "SUCCESS",
            "duration": 0.0,
            "error": None,
            "metadata": {
                "args": args,
                "command": command,
                "cwd": cwd,
                "disposable": disposable,
                "env": env,
                "files": files,
                "hostname": hostname,
                "image": image,
                "result": {
                    "resources": resources,
                    "state": state,
                    "stderr": {
                        "value": stderr,
                        "encoding": "ascii",
                        "truncated": False,
                    },
                    "stdout": {
                        "value": stdout,
                        "encoding": "ascii",
                        "truncated": False,
                    },
                },
                "shell": shell,
                "stdin": stdin,
                "timeout": timeout,
                "truncate_output_at": truncate_output_at,
                "preserve_env": preserve_env,
            },
            "result": {"image": output_uuid, "tag": None},
        }

    async def spawn(
        self,
        *,
        command: str,
        image: str,
        hostname: str,
        args: list[str] | tuple[str, ...] | None = None,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        cwd: str,
        disposable: bool = False,
        stdin: StreamValue = None,
        timeout: int = 60,
        truncate_output_at: int = 65535,
        files: Mapping[str, FileSpecValue] | None = None,
        preserve_env: bool = False,
    ) -> str:
        request = TokenFactorySandboxApi._spawn_body(
            command=command,
            image=image,
            hostname=hostname,
            args=args,
            shell=shell,
            env=env,
            cwd=cwd,
            disposable=disposable,
            stdin=stdin,
            timeout=timeout,
            truncate_output_at=truncate_output_at,
            files=files,
            preserve_env=preserve_env,
        )
        self.calls.append({"method": "spawn", **deepcopy(request)})
        return await self._execute(
            command=command,
            image=image,
            hostname=hostname,
            args=args,
            shell=shell,
            env=env,
            cwd=cwd,
            disposable=disposable,
            stdin=stdin,
            timeout=timeout,
            truncate_output_at=truncate_output_at,
            files=files,
            preserve_env=preserve_env,
        )

    async def operation(self, operation_id: str) -> dict[str, Any]:
        self.calls.append({"method": "operation", "operation": operation_id})
        return deepcopy(self._operations[operation_id])

    async def cancel(self, operation_id: str) -> None:
        self.calls.append({"method": "cancel", "operation": operation_id})
        operation = self._operations[operation_id]
        operation["status"] = "CANCELLED"

    async def run(
        self,
        *,
        command: str,
        image: str,
        hostname: str,
        args: list[str] | tuple[str, ...] | None = None,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        cwd: str,
        disposable: bool = False,
        stdin: StreamValue = None,
        timeout: int = 60,
        truncate_output_at: int = 65535,
        files: Mapping[str, FileSpecValue] | None = None,
        preserve_env: bool = False,
        client_timeout_s: float | None = None,
    ) -> RunResult:
        request = TokenFactorySandboxApi._spawn_body(
            command=command,
            image=image,
            hostname=hostname,
            args=args,
            shell=shell,
            env=env,
            cwd=cwd,
            disposable=disposable,
            stdin=stdin,
            timeout=timeout,
            truncate_output_at=truncate_output_at,
            files=files,
            preserve_env=preserve_env,
        )
        self.calls.append(
            {"method": "run", **deepcopy(request), "client_timeout_s": client_timeout_s},
        )
        operation_id = await self._execute(
            command=command,
            image=image,
            hostname=hostname,
            args=args,
            shell=shell,
            env=env,
            cwd=cwd,
            disposable=disposable,
            stdin=stdin,
            timeout=timeout,
            truncate_output_at=truncate_output_at,
            files=files,
            preserve_env=preserve_env,
        )
        return _run_result(self._operations[operation_id], {})
