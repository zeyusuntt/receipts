from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import httpx2
from openai import APIConnectionError, APITimeoutError
from pydantic import BaseModel

import receipts.llm as llm_module
from receipts.cost import CostMeter, TokenUsage
from receipts.llm import (
    AssistantTurn,
    FakeModel,
    MalformedToolCall,
    ModelConfig,
    TokenFactoryClient,
    ToolCall,
    load_config,
)


SUPER = "nvidia/nemotron-3-super-120b-a12b"
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"


class Answer(BaseModel):
    answer: int


class _FakeStatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _FakeCompletions:
    def __init__(self, scripted: list[Any]):
        self.scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self.scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeSDK:
    def __init__(self, scripted: list[Any]):
        self.completions = _FakeCompletions(scripted)
        self.chat = SimpleNamespace(completions=self.completions)


def _response(
    *,
    content: str | None = None,
    tool_calls: list[Any] | None = None,
    prompt_tokens: int = 11,
    completion_tokens: int = 7,
    reasoning_tokens: int | None = 3,
    finish_reason: str | None = None,
) -> Any:
    details = SimpleNamespace(reasoning_tokens=reasoning_tokens)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        completion_tokens_details=details,
    )
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=usage,
    )


def _sdk_tool_call(name: str, arguments: str, call_id: str = "call-1") -> Any:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _config(**overrides: Any) -> ModelConfig:
    values = {
        "model": SUPER,
        "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "max_tokens": 2_000,
    }
    values.update(overrides)
    return ModelConfig(**values)


async def test_complete_json_falls_back_and_feeds_validation_error_back():
    sdk = _FakeSDK(
        [
            _FakeStatusError(400),
            _response(content='{"answer": "not-an-integer"}'),
            _response(content='{"answer": 7}'),
        ],
    )
    client = TokenFactoryClient(_config(), client=sdk)

    result = await client.complete_json("system", "question", Answer)

    assert result == Answer(answer=7)
    calls = sdk.completions.calls
    assert calls[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "Answer",
            "schema": Answer.model_json_schema(),
            "strict": True,
        },
    }
    assert calls[1]["response_format"] == {"type": "json_object"}
    assert "single JSON object matching this schema" in calls[1]["messages"][0]["content"]
    assert "previous answer did not match" in calls[2]["messages"][1]["content"]
    assert "valid integer" in calls[2]["messages"][1]["content"]


async def test_complete_json_stops_after_two_validation_retries():
    sdk = _FakeSDK(
        [
            _FakeStatusError(422),
            _response(content="{}"),
            _response(content="{}"),
            _response(content="{}"),
        ],
    )
    client = TokenFactoryClient(_config(), client=sdk)

    with pytest.raises(RuntimeError, match="after 3 attempt"):
        await client.complete_json("system", "question", Answer)

    assert len(sdk.completions.calls) == 4


async def test_complete_json_attaches_plan_usage_without_changing_output_schema():
    from receipts.agent.planner import Plan

    sdk = _FakeSDK(
        [
            _response(
                content=(
                    '{"hypothesis":"broken subtraction",'
                    '"files_to_edit":["calc/__init__.py"],'
                    '"approach":"Fix subtraction."}'
                ),
                prompt_tokens=123,
                completion_tokens=45,
                reasoning_tokens=6,
                finish_reason="stop",
            ),
        ],
    )
    client = TokenFactoryClient(_config(), client=sdk)

    plan = await client.complete_json("system", "issue", Plan)

    assert plan.usage == TokenUsage(prompt=123, completion=45, reasoning=6)
    assert plan.finish_reason == "stop"
    output_schema = sdk.completions.calls[0]["response_format"]["json_schema"]["schema"]
    assert set(output_schema["properties"]) == {
        "hypothesis",
        "files_to_edit",
        "approach",
    }


async def test_chat_surfaces_malformed_tool_arguments_as_a_turn():
    sdk = _FakeSDK(
        [
            _response(
                content="I will inspect the repository.",
                tool_calls=[_sdk_tool_call("run_command", '{"cmd":')],
                finish_reason="tool_calls",
            ),
        ],
    )
    client = TokenFactoryClient(_config(), client=sdk)

    turn = await client.chat(
        [{"role": "user", "content": "Find the failure"}],
        [{"type": "function", "function": {"name": "run_command"}}],
    )

    assert isinstance(turn, MalformedToolCall)
    assert turn.tool_name == "run_command"
    assert turn.tool_call_id == "call-1"
    assert turn.raw_arguments == '{"cmd":'
    assert turn.usage == TokenUsage(prompt=11, completion=7, reasoning=3)
    assert turn.finish_reason == "tool_calls"
    call = sdk.completions.calls[0]
    assert call["temperature"] == 1.0
    assert call["top_p"] == 0.95
    assert call["max_tokens"] == 2_000
    assert call["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False},
    }


async def test_malformed_call_keeps_name_and_id_for_worker_logging():
    sdk = _FakeSDK(
        [
            _response(
                tool_calls=[
                    _sdk_tool_call(
                        "execute",
                        '["arguments", "must", "be", "an", "object"]',
                        "malformed-alias-7",
                    ),
                ],
            ),
        ],
    )
    client = TokenFactoryClient(_config(), client=sdk)

    turn = await client.chat(
        [{"role": "user", "content": "Run the tests"}],
        [{"type": "function", "function": {"name": "run_command"}}],
    )

    assert isinstance(turn, MalformedToolCall)
    assert turn.tool_name == "execute"
    assert turn.tool_call_id == "malformed-alias-7"


async def test_malformed_call_keeps_all_raw_call_metadata_in_order():
    sdk = _FakeSDK(
        [
            _response(
                tool_calls=[
                    _sdk_tool_call("run_command", '{"cmd":', "malformed-first"),
                    _sdk_tool_call("read_file", '{"path": "README.md"}', "valid-second"),
                    _sdk_tool_call("edit_file", "[]", "malformed-third"),
                ],
            ),
        ],
    )
    client = TokenFactoryClient(_config(), client=sdk)

    turn = await client.chat(
        [{"role": "user", "content": "Inspect the repository"}],
        [{"type": "function", "function": {"name": "read_file"}}],
    )

    assert isinstance(turn, MalformedToolCall)
    assert turn.tool_calls == []
    assert [call.model_dump() for call in turn.raw_tool_calls] == [
        {"id": "malformed-first", "name": "run_command", "malformed_args": True},
        {"id": "valid-second", "name": "read_file", "malformed_args": False},
        {"id": "malformed-third", "name": "edit_file", "malformed_args": True},
    ]


async def test_malformed_turn_with_a_later_nameless_call_is_still_a_malformed_turn():
    """Logging metadata must never turn a malformed turn into a model error."""

    later = _sdk_tool_call("read_file", '{"path": "README.md"}', "later")
    later.id = None
    later.function.name = None
    sdk = _FakeSDK(
        [
            _response(
                tool_calls=[
                    _sdk_tool_call("run_command", '{"cmd":', "malformed-first"),
                    later,
                ],
            ),
        ],
    )
    client = TokenFactoryClient(_config(), client=sdk)

    turn = await client.chat(
        [{"role": "user", "content": "Inspect the repository"}],
        [{"type": "function", "function": {"name": "read_file"}}],
    )

    assert isinstance(turn, MalformedToolCall)
    assert turn.tool_calls == []
    assert [call.model_dump() for call in turn.raw_tool_calls] == [
        {"id": "malformed-first", "name": "run_command", "malformed_args": True},
        {"id": "", "name": "", "malformed_args": False},
    ]


@pytest.mark.parametrize("status_code", [429, 503])
async def test_chat_retries_transient_api_errors_three_times(status_code: int):
    sdk = _FakeSDK(
        [
            _FakeStatusError(status_code),
            _FakeStatusError(status_code),
            _FakeStatusError(status_code),
            _response(content="recovered"),
        ],
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    client = TokenFactoryClient(_config(), client=sdk, sleep=fake_sleep)

    turn = await client.chat([{"role": "user", "content": "hello"}], [])

    assert turn.content == "recovered"
    assert turn.retries == {"429" if status_code == 429 else "5xx": 3}
    assert delays == [1.0, 2.0, 4.0]
    assert len(sdk.completions.calls) == 4


async def test_chat_reports_two_429_retries_on_the_successful_turn():
    sdk = _FakeSDK(
        [
            _FakeStatusError(429),
            _FakeStatusError(429),
            _response(content="recovered"),
        ],
    )

    async def fake_sleep(delay: float) -> None:
        pass

    client = TokenFactoryClient(_config(), client=sdk, sleep=fake_sleep)

    turn = await client.chat([{"role": "user", "content": "hello"}], [])

    assert turn.retries == {"429": 2}


async def test_chat_reports_no_retries_when_the_first_request_succeeds():
    client = TokenFactoryClient(
        _config(),
        client=_FakeSDK([_response(content="first try")]),
    )

    turn = await client.chat([{"role": "user", "content": "hello"}], [])

    assert turn.retries == {}


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (TimeoutError("request timed out"), "timeout"),
        (ConnectionError("connection reset"), "connection"),
        (
            APITimeoutError(httpx2.Request("GET", "https://example.invalid")),
            "timeout",
        ),
        (
            APIConnectionError(
                request=httpx2.Request("GET", "https://example.invalid"),
            ),
            "connection",
        ),
    ],
)
async def test_chat_counts_timeout_and_connection_retries(error: Exception, kind: str):
    sdk = _FakeSDK([error, _response(content="recovered")])

    async def fake_sleep(delay: float) -> None:
        pass

    client = TokenFactoryClient(_config(), client=sdk, sleep=fake_sleep)

    turn = await client.chat([{"role": "user", "content": "hello"}], [])

    assert turn.retries == {kind: 1}


def test_cost_meter_accumulates_model_usage_and_sandbox_seconds():
    meter = CostMeter()
    meter.add_usage(
        SUPER,
        TokenUsage(prompt=1_000_000, completion=500_000, reasoning=100_000),
    )
    meter.add_usage(
        SUPER,
        TokenUsage(prompt=500_000, completion=500_000, reasoning=25_000),
    )
    meter.add_usage(NANO, TokenUsage(prompt=250_000, completion=250_000))
    meter.add_sandbox_seconds(1.25)
    meter.add_sandbox_seconds(2.75)

    summary = meter.summary()

    assert summary["models"][SUPER] == {
        "prompt_tokens": 1_500_000,
        "completion_tokens": 1_000_000,
        "reasoning_tokens": 125_000,
        "estimated_dollars": 0.33,
    }
    assert summary["models"][NANO]["estimated_dollars"] == 0.075
    assert summary["estimated_dollars"] == 0.405
    assert summary["sandbox_seconds"] == 4.0
    assert summary["pricing_is_estimate"] is True


def test_dotenv_takes_precedence_over_process_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=dotenv-secret\n"
        "OPENAI_BASE_URL=https://dotenv.example/v1/\n"
        f"NEMOTRON_MODEL={SUPER}\n",
        encoding="utf-8",
    )
    process_env = {
        "OPENAI_API_KEY": "process-secret",
        "OPENAI_BASE_URL": "https://process.example/v1/",
        "NEMOTRON_MODEL": NANO,
    }
    captured: dict[str, Any] = {}
    fake_sdk = _FakeSDK([])

    def fake_openai(**kwargs: Any) -> _FakeSDK:
        captured.update(kwargs)
        return fake_sdk

    monkeypatch.setattr(llm_module, "AsyncOpenAI", fake_openai)

    config = load_config(env_path=env_file, environ=process_env)
    TokenFactoryClient(config, env_path=env_file, environ=process_env)

    assert config.model == SUPER
    assert config.base_url == "https://dotenv.example/v1/"
    assert captured["api_key"] == "dotenv-secret"
    assert captured["base_url"] == "https://dotenv.example/v1/"
    assert captured["timeout"] == 180
    assert captured["max_retries"] == 0


async def test_fake_model_scripts_both_interfaces_and_records_requests():
    turn = AssistantTurn(
        content=None,
        tool_calls=[ToolCall(name="finish", arguments={"summary": "done"}, id="call-2")],
        usage=TokenUsage(prompt=5, completion=2),
    )
    fake = FakeModel(turns=[turn], json_objects=[{"answer": 9}])

    result = await fake.complete_json("planner", "make a plan", Answer)
    actual_turn = await fake.chat(
        [{"role": "user", "content": "work"}],
        [{"type": "function", "function": {"name": "finish"}}],
    )

    assert result == Answer(answer=9)
    assert actual_turn == turn
    assert fake.requests == [
        {
            "kind": "complete_json",
            "system": "planner",
            "user": "make a plan",
            "schema": Answer,
        },
        {
            "kind": "chat",
            "messages": [{"role": "user", "content": "work"}],
            "tools": [{"type": "function", "function": {"name": "finish"}}],
        },
    ]


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("RECEIPTS_LIVE") != "1",
    reason="set RECEIPTS_LIVE=1 to call Token Factory",
)
async def test_live_super_returns_one_field_json():
    class LiveAnswer(BaseModel):
        answer: str

    config = load_config()
    client = TokenFactoryClient(config)

    result = await client.complete_json(
        "Reply with the requested JSON only.",
        'Return {"answer": "ok"}.',
        LiveAnswer,
    )

    assert result.answer == "ok"
