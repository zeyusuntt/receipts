import asyncio
import hashlib
import importlib
import json
import logging
from copy import deepcopy
from pathlib import Path

import httpx
import pytest


BASE_URL = "https://api.tokenfactory.nebius.com/sandboxes"
API_KEY = "tf-secret-key"
PROJECT_ID = "aiproject-test"
IMAGE_UUID = "11111111-1111-1111-1111-111111111111"
OUTPUT_UUID = "22222222-2222-2222-2222-222222222222"


def _module():
    try:
        return importlib.import_module("receipts.sandbox.tokenfactory_api")
    except ModuleNotFoundError:
        pytest.fail("the Token Factory sandbox API module is not implemented")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _operation(status: str = "SUCCESS") -> dict:
    return {
        "kind": "instance",
        "status": status,
        "duration": 1.25,
        "error": None,
        "metadata": {
            "args": ["-c", "print('ok')"],
            "command": "python",
            "cwd": "/repo",
            "disposable": False,
            "env": {"PYTHONUNBUFFERED": "1"},
            "files": {},
            "hostname": "runner",
            "image": IMAGE_UUID,
            "result": {
                "resources": {
                    "block_input": 0,
                    "block_output": 8,
                    "cost": 0.0042,
                    "elapsed_time": 1.125,
                    "involuntary_switches": 1,
                    "max_rss": 4096,
                    "monotonic_time": 1.12,
                    "page_faults": 12,
                    "page_faults_io": 0,
                    "shared_memory": 0,
                    "signals": 0,
                    "swaps": 0,
                    "system_cpu_time": 0.05,
                    "unshared_memory": 0,
                    "user_cpu_time": 0.25,
                    "voluntary_switches": 3,
                },
                "state": {
                    "continued": False,
                    "core_dump": False,
                    "exit_code": 7,
                    "pid": 42,
                    "signal": 0,
                    "stopped": False,
                    "timed_out": False,
                },
                "stderr": {
                    "value": "d2FybmluZwo=",
                    "encoding": "base64",
                    "truncated": False,
                },
                "stdout": {
                    "value": "ok\n",
                    "encoding": "ascii",
                    "truncated": False,
                },
            },
            "shell": False,
            "stdin": {"value": "", "encoding": "ascii", "truncated": False},
            "timeout": 30,
            "truncate_output_at": 65535,
            "preserve_env": True,
        },
        "result": {"image": OUTPUT_UUID, "tag": None},
    }


async def test_every_http_request_has_token_factory_headers():
    module = _module()
    requests: list[httpx.Request] = []
    digest = hashlib.sha256(b"already there").hexdigest()

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        assert request.headers["Project"] == PROJECT_ID
        path = request.url.path
        if path.endswith("/v1/whoami"):
            return httpx.Response(200, json={"permissions": {}, "limits": {}})
        if path.endswith(f"/v1/inspect/{IMAGE_UUID}/"):
            return httpx.Response(200, json={"uuid": IMAGE_UUID, "tag": None})
        if path.endswith(f"/v1/inspect/{IMAGE_UUID}/list"):
            return httpx.Response(200, json={"files": []})
        if path.endswith(f"/v1/inspect/{IMAGE_UUID}/download"):
            return httpx.Response(200, content=b"contents")
        if path.endswith(f"/v1/files/{digest}"):
            if request.method == "GET":
                return httpx.Response(200, json={"uuid": "file-1", "sha256": digest})
            return httpx.Response(200)
        if path.endswith("/v1/instances"):
            return httpx.Response(200, json={"uuid": "operation-1"})
        if path.endswith("/v1/operations/operation-1"):
            if request.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(200, json=_operation("PENDING"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        await api.whoami()
        await api.image(IMAGE_UUID)
        await api.list_files(IMAGE_UUID, "/repo")
        assert await api.download(IMAGE_UUID, "/repo/file.txt") == b"contents"
        assert (await api.upload(b"already there")).sha256 == digest
        operation_id = await api.spawn(
            command="true",
            image=IMAGE_UUID,
            hostname="runner",
            cwd="/repo",
        )
        await api.operation(operation_id)
        await api.cancel(operation_id)

    assert len(requests) == 9  # upload of an existing file is HEAD then GET for its uuid


async def test_bounded_download_stops_stream_after_limit_is_exceeded():
    module = _module()

    class RecordingStream(httpx.AsyncByteStream):
        def __init__(self):
            self.yielded = 0
            self.closed = False

        async def __aiter__(self):
            for chunk in (b"abc", b"def", b"unread"):
                self.yielded += 1
                yield chunk

        async def aclose(self):
            self.closed = True

    stream = RecordingStream()

    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, request=request)

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        with pytest.raises(RuntimeError, match="size cap of 5 bytes"):
            await api.download(IMAGE_UUID, "/tmp/archive.tar", max_bytes=5)

    assert stream.yielded == 2
    assert stream.closed is True


async def test_missing_project_response_is_clear_and_is_not_retried():
    module = _module()
    calls = 0

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            json={"detail": 'Missing "Project" header'},
            request=request,
        )

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        with pytest.raises(module.TokenFactoryApiError) as caught:
            await api.whoami()

    assert calls == 1
    assert caught.value.status_code == 400
    assert 'Missing "Project" header' in str(caught.value)


async def test_image_by_tag_resolves_relative_redirect_without_following_it():
    module = _module()
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert dict(request.url.params) == {"tag": "swerebenchv2/example:1-abc"}
        return httpx.Response(
            302,
            headers={"Location": f"{IMAGE_UUID}/"},
            request=request,
        )

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        found = await api.image_by_tag("swerebenchv2/example:1-abc")

    assert found == IMAGE_UUID
    assert len(requests) == 1


async def test_image_by_tag_returns_none_on_404():
    module = _module()

    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="image not found", request=request)

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        assert await api.image_by_tag("missing") is None


async def test_spawn_serializes_the_sdk_request_shape():
    module = _module()
    uploaded_sha256 = "a" * 64
    bodies: list[dict] = []

    expected = {
        "command": "python",
        "image": IMAGE_UUID,
        "hostname": "runner",
        "args": ["-c", "print('ok')"],
        "shell": False,
        "env": {"PYTHONUNBUFFERED": "1"},
        "cwd": "/repo",
        "disposable": False,
        "stdin": {"value": "", "encoding": "ascii", "truncated": False},
        "timeout": 30,
        "truncate_output_at": 65535,
        "files": {
            "/repo/input.txt": {
                "uuid": uploaded_sha256,
                "mode": "0640",
                "uid": 1000,
                "gid": 1000,
            },
        },
        "preserve_env": True,
    }

    async def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"uuid": "operation-1"}, request=request)

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        operation_id = await api.spawn(
            command="python",
            image=IMAGE_UUID,
            hostname="runner",
            args=["-c", "print('ok')"],
            shell=False,
            env={"PYTHONUNBUFFERED": "1"},
            cwd="/repo",
            disposable=False,
            stdin=None,
            timeout=30,
            truncate_output_at=65535,
            files={
                "/repo/input.txt": module.InstanceFileSpec(
                    uuid=uploaded_sha256,
                    mode="0640",
                    uid=1000,
                    gid=1000,
                ),
            },
            preserve_env=True,
        )

    assert operation_id == "operation-1"
    assert bodies == [expected]


async def test_run_polls_to_terminal_and_parses_the_sdk_result_shape():
    module = _module()
    statuses = iter(["PENDING", "EXECUTING", "SUCCESS"])
    sleeps: list[float] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"uuid": "operation-1"}, request=request)
        return httpx.Response(200, json=_operation(next(statuses)), request=request)

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(
            API_KEY,
            PROJECT_ID,
            client=client,
            sleep=sleep,
        )
        result = await api.run(
            command="python",
            image=IMAGE_UUID,
            hostname="runner",
            args=["-c", "print('ok')"],
            env={"PYTHONUNBUFFERED": "1"},
            cwd="/repo",
            disposable=False,
            timeout=30,
            preserve_env=True,
        )

    assert result == module.RunResult(
        exit_code=7,
        stdout="ok\n",
        stderr="warning\n",
        image_uuid=OUTPUT_UUID,
        duration_s=1.125,
        cost=0.0042,
        status="SUCCESS",
        error=None,
        retries={},
        operation_id="operation-1",
        timed_out=False,
    )
    assert sleeps == [0.1, 0.2]


async def test_run_cancels_an_accepted_operation_on_client_timeout():
    module = _module()
    methods: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json={"uuid": "operation-1"}, request=request)
        if request.method == "DELETE":
            return httpx.Response(204, request=request)
        return httpx.Response(200, json=_operation("PENDING"), request=request)

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        with pytest.raises(TimeoutError, match="operation-1"):
            await api.run(
                command="sleep",
                image=IMAGE_UUID,
                hostname="runner",
                cwd="/repo",
                client_timeout_s=0.01,
            )

    assert methods.count("POST") == 1
    assert methods.count("DELETE") == 1


async def test_run_cancels_an_accepted_operation_on_http_transport_timeout():
    module = _module()
    methods: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json={"uuid": "operation-1"}, request=request)
        if request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise httpx.ReadTimeout("poll timed out", request=request)

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        with pytest.raises(TimeoutError, match="operation-1"):
            await api.run(
                command="sleep",
                image=IMAGE_UUID,
                hostname="runner",
                cwd="/repo",
            )

    assert methods == ["POST", "GET", "DELETE"]


async def test_run_counts_429_retry_without_resending_accepted_spawn():
    module = _module()
    spawn_calls = 0
    poll_calls = 0
    sleeps: list[float] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal spawn_calls, poll_calls
        if request.method == "POST":
            spawn_calls += 1
            return httpx.Response(200, json={"uuid": "operation-1"}, request=request)
        poll_calls += 1
        if poll_calls == 1:
            return httpx.Response(429, text="slow down", request=request)
        return httpx.Response(200, json=_operation(), request=request)

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(
            API_KEY,
            PROJECT_ID,
            client=client,
            sleep=sleep,
        )
        result = await api.run(
            command="true",
            image=IMAGE_UUID,
            hostname="runner",
            cwd="/repo",
        )

    assert spawn_calls == 1
    assert poll_calls == 2
    assert result.retries == {"429": 1}
    assert sleeps == [1.0]


async def test_upload_skips_post_when_sha256_already_exists():
    module = _module()
    data = b"uploaded contents"
    digest = hashlib.sha256(data).hexdigest()
    methods: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        assert request.url.path.endswith(f"/v1/files/{digest}")
        if request.method == "GET":
            return httpx.Response(200, json={"uuid": "existing-file-1", "sha256": digest}, request=request)
        return httpx.Response(200, request=request)

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        uploaded = await api.upload(data)
        assert (uploaded.uuid, uploaded.sha256) == ("existing-file-1", digest)

    assert methods == ["HEAD", "GET"]


async def test_upload_posts_octet_stream_after_head_404():
    module = _module()
    data = b"new contents"
    digest = hashlib.sha256(data).hexdigest()
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "HEAD":
            return httpx.Response(404, request=request)
        assert request.headers["Content-Type"] == "application/octet-stream"
        assert request.content == data
        return httpx.Response(
            200,
            json={"uuid": "uploaded-file-1", "sha256": digest},
            request=request,
        )

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        uploaded = await api.upload(data)
        assert (uploaded.uuid, uploaded.sha256) == ("uploaded-file-1", digest)

    assert [request.method for request in requests] == ["HEAD", "POST"]


async def test_download_returns_none_on_404():
    module = _module()

    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            text="File not found in stored service",
            request=request,
        )

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        assert await api.download(IMAGE_UUID, "/missing") is None


async def test_from_env_prefers_dotenv_key_and_nebius_ai_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _module()
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "OPENAI_API_KEY=dotenv-key\n"
        "NEBIUS_AI_PROJECT=aiproject-dotenv\n"
        "NEBIUS_PROJECT_ID=aiproject-fallback\n",
        encoding="utf-8",
    )
    captured: dict[str, str] = {}

    original_init = module.TokenFactorySandboxApi.__init__

    def capture_init(self, api_key, project_id, **kwargs):
        captured.update(api_key=api_key, project_id=project_id)
        original_init(self, api_key, project_id, **kwargs)

    monkeypatch.setattr(module.TokenFactorySandboxApi, "__init__", capture_init)
    api = module.TokenFactorySandboxApi.from_env(
        environ={
            "OPENAI_API_KEY": "shell-key",
            "NEBIUS_AI_PROJECT": "aiproject-shell",
        },
        dotenv_path=dotenv,
    )
    try:
        assert captured == {
            "api_key": "dotenv-key",
            "project_id": "aiproject-dotenv",
        }
    finally:
        await api.aclose()


async def test_secret_is_absent_from_reprs_errors_and_logs(caplog: pytest.LogCaptureFixture):
    module = _module()
    caplog.set_level(logging.DEBUG)

    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            text=f"rejected credential {API_KEY}",
            request=request,
        )

    async with _client(handle) as client:
        api = module.TokenFactorySandboxApi(API_KEY, PROJECT_ID, client=client)
        assert API_KEY not in repr(api)
        with pytest.raises(module.TokenFactoryApiError) as caught:
            await api.whoami()

    assert API_KEY not in str(caught.value)
    assert API_KEY not in repr(caught.value)
    assert API_KEY not in caplog.text


async def test_fake_forks_are_isolated_and_parent_is_immutable():
    module = _module()

    def write_a(tree: dict[str, bytes]):
        tree["/repo/a.txt"] = b"a"
        return 0, "a out", "", tree

    def write_b(tree: dict[str, bytes]):
        tree["/repo/b.txt"] = b"b"
        return 0, "b out", "", tree

    fake = module.FakeTokenFactorySandboxApi(
        images={IMAGE_UUID: {"/repo/original.txt": b"original"}},
        tags={"base": IMAGE_UUID},
        handlers={"write-a": write_a, "write-b": write_b},
    )

    assert await fake.image_by_tag("base") == IMAGE_UUID
    first = await fake.run(
        command="write-a",
        image=IMAGE_UUID,
        hostname="runner",
        cwd="/repo",
        disposable=False,
    )
    second = await fake.run(
        command="write-b",
        image=IMAGE_UUID,
        hostname="runner",
        cwd="/repo",
        disposable=False,
    )

    assert first.image_uuid != second.image_uuid
    assert await fake.download(IMAGE_UUID, "/repo/a.txt") is None
    assert await fake.download(IMAGE_UUID, "/repo/b.txt") is None
    assert await fake.download(first.image_uuid, "/repo/a.txt") == b"a"
    assert await fake.download(first.image_uuid, "/repo/b.txt") is None
    assert await fake.download(second.image_uuid, "/repo/a.txt") is None
    assert await fake.download(second.image_uuid, "/repo/b.txt") == b"b"


async def test_fake_injects_uploaded_files_and_records_calls():
    module = _module()
    handler_inputs: list[dict[str, bytes]] = []

    def inspect(tree: dict[str, bytes]):
        handler_inputs.append(deepcopy(tree))
        return 0, tree["/tmp/input.txt"].decode(), "", tree

    fake = module.FakeTokenFactorySandboxApi(
        images={IMAGE_UUID: {"/repo/original.txt": b"original"}},
        handlers={"inspect": inspect},
    )
    digest = (await fake.upload(b"payload")).uuid
    result = await fake.run(
        command="inspect",
        image=IMAGE_UUID,
        hostname="runner",
        cwd="/repo",
        disposable=False,
        files={
            "/tmp/input.txt": module.InstanceFileSpec(
                uuid=digest,
                mode="0600",
                uid=0,
                gid=0,
            ),
        },
    )

    assert handler_inputs == [
        {
            "/repo/original.txt": b"original",
            "/tmp/input.txt": b"payload",
        },
    ]
    assert result.stdout == "payload"
    assert await fake.download(result.image_uuid, "/tmp/input.txt") == b"payload"
    assert [call["method"] for call in fake.calls if call["method"] in {"upload", "run"}] == [
        "upload",
        "run",
    ]
    run_call = next(call for call in fake.calls if call["method"] == "run")
    assert run_call == {
        "method": "run",
        "command": "inspect",
        "image": IMAGE_UUID,
        "hostname": "runner",
        "args": [],
        "shell": False,
        "env": {},
        "cwd": "/repo",
        "disposable": False,
        "stdin": {"value": "", "encoding": "ascii", "truncated": False},
        "timeout": 60,
        "truncate_output_at": 65535,
        "files": {
            "/tmp/input.txt": {
                "uuid": digest,
                "mode": "0600",
                "uid": 0,
                "gid": 0,
            },
        },
        "preserve_env": False,
        "client_timeout_s": None,
    }


async def test_fake_cancels_non_terminal_operation_on_client_timeout():
    module = _module()

    class NeverTerminalFake(module.FakeTokenFactorySandboxApi):
        async def _execute(self, **kwargs):
            operation_id = await super()._execute(**kwargs)
            self._operations[operation_id]["status"] = "PENDING"
            return operation_id

    fake = NeverTerminalFake(
        images={IMAGE_UUID: {}},
        handlers={"wait": lambda tree: (0, "", "", tree)},
    )

    with pytest.raises(TimeoutError, match="fake-operation-1"):
        await fake.run(
            command="wait",
            image=IMAGE_UUID,
            hostname="runner",
            cwd="/repo",
            client_timeout_s=0.01,
        )

    assert {"method": "cancel", "operation": "fake-operation-1"} in fake.calls


async def test_fake_bounded_download_refuses_content_over_limit():
    module = _module()
    fake = module.FakeTokenFactorySandboxApi(
        images={IMAGE_UUID: {"/tmp/archive.tar": b"123456"}},
    )

    with pytest.raises(RuntimeError, match="size cap of 5 bytes"):
        await fake.download(IMAGE_UUID, "/tmp/archive.tar", max_bytes=5)


async def test_fake_rejects_output_limits_the_live_api_rejects():
    module = _module()
    fake = module.FakeTokenFactorySandboxApi(images={IMAGE_UUID: {}}, handlers={"true": lambda tree: (0, "", "", tree)})

    with pytest.raises(module.TokenFactoryApiError) as error:
        await fake.spawn(command="true", image=IMAGE_UUID, hostname="h", cwd="/", truncate_output_at=10 * 1024 * 1024)

    assert error.value.status_code == 400
    assert "truncate_output_at" in error.value.detail


async def test_truncated_output_is_reported_on_the_run_result():
    module = _module()
    fake = module.FakeTokenFactorySandboxApi(
        images={IMAGE_UUID: {}},
        handlers={"loud": lambda tree: (0, "x" * 500, "", tree)},
    )

    result = await fake.run(command="loud", image=IMAGE_UUID, hostname="h", cwd="/", truncate_output_at=100)

    assert result.output_truncated is True
    assert len(result.stdout) == 100
    quiet = await fake.run(command="loud", image=IMAGE_UUID, hostname="h", cwd="/", truncate_output_at=1000)
    assert quiet.output_truncated is False
